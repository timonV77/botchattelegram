#!/usr/bin/env python3
"""
Мониторинг баланса Polza.ai с алертами админам в ВК.

Запускается раз в N минут через systemd timer.
- Тянет баланс через https://polza.ai/api/v1/balance
- При баланс <= WARNING_THRESHOLD шлёт уведомление в ВК (но не чаще 1 раз в час)
- При баланс <= CRITICAL_THRESHOLD шлёт уведомление чаще (1 раз в 15 мин)
- При восстановлении баланса (>WARNING_THRESHOLD после warning) шлёт "ОК"

State хранится в /var/lib/vkbot_balance_monitor/state.json.
Конфиг читается из /root/botchattelegram/.env.
"""
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional
from urllib import request, parse, error
from dotenv import load_dotenv

# === Настройки ===
ENV_PATH = "/root/botchattelegram/.env"
STATE_DIR = Path("/var/lib/vkbot_balance_monitor")
STATE_FILE = STATE_DIR / "state.json"

WARNING_THRESHOLD = 50.0    # рубли
CRITICAL_THRESHOLD = 10.0   # рубли
WARNING_NOTIFY_INTERVAL = 60 * 60       # 1 час
CRITICAL_NOTIFY_INTERVAL = 15 * 60      # 15 минут

POLZA_BALANCE_URL = "https://polza.ai/api/v1/balance"
VK_API_URL = "https://api.vk.com/method/messages.send"
VK_API_VERSION = "5.199"


# === Логирование (всё в stderr → systemd journal) ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("polza_balance_monitor")


def load_env() -> dict:
    load_dotenv(ENV_PATH)
    polza_key = os.getenv("VK_POLZA_API_KEY") or os.getenv("POLZA_API_KEY")
    vk_token = os.getenv("VK_TOKEN")
    admin_ids_raw = os.getenv("VK_ADMIN_IDS", "")
    admin_ids = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip().isdigit()]

    missing = [k for k, v in {"VK_POLZA_API_KEY/POLZA_API_KEY": polza_key,
                              "VK_TOKEN": vk_token,
                              "VK_ADMIN_IDS": admin_ids}.items() if not v]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        sys.exit(2)

    return {"polza_key": polza_key, "vk_token": vk_token, "admin_ids": admin_ids}


def fetch_polza_balance(polza_key: str) -> Optional[float]:
    req = request.Request(
        POLZA_BALANCE_URL,
        headers={"Authorization": f"Bearer {polza_key}"},
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            amount_str = data.get("amount")
            if amount_str is None:
                log.error("Polza balance response missing 'amount': %s", data)
                return None
            return float(amount_str)
    except (error.URLError, error.HTTPError, json.JSONDecodeError, ValueError) as e:
        log.error("Failed to fetch Polza balance: %s", e)
        return None


def vk_send_message(vk_token: str, user_id: int, text: str) -> bool:
    payload = {
        "user_id": user_id,
        "message": text,
        "random_id": int(time.time() * 1000) % (2**31),
        "v": VK_API_VERSION,
        "access_token": vk_token,
    }
    body = parse.urlencode(payload).encode("utf-8")
    try:
        with request.urlopen(VK_API_URL, data=body, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "error" in data:
                log.error("VK API error sending to %s: %s", user_id, data["error"])
                return False
            return True
    except Exception as e:
        log.error("VK send to %s failed: %s", user_id, e)
        return False


def notify_admins(vk_token: str, admin_ids: list, text: str):
    for admin_id in admin_ids:
        ok = vk_send_message(vk_token, admin_id, text)
        log.info("Notify admin %s: %s", admin_id, "OK" if ok else "FAIL")


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_level": "ok", "last_notify_ts": 0, "last_balance": None}


def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def classify(balance: float) -> str:
    if balance <= CRITICAL_THRESHOLD:
        return "critical"
    if balance <= WARNING_THRESHOLD:
        return "warning"
    return "ok"


def main():
    cfg = load_env()
    balance = fetch_polza_balance(cfg["polza_key"])
    if balance is None:
        log.error("Could not get balance, skipping run")
        sys.exit(1)

    log.info("Polza balance = %.2f ₽", balance)

    state = load_state()
    now = int(time.time())
    level = classify(balance)

    notify_text = None

    if level == "critical":
        interval = CRITICAL_NOTIFY_INTERVAL
        if state["last_level"] != "critical" or (now - state["last_notify_ts"]) >= interval:
            notify_text = (
                f"🚨 КРИТИЧНО: баланс Polza.ai = {balance:.2f} ₽\n"
                f"Порог: {CRITICAL_THRESHOLD:.0f} ₽\n"
                f"Срочно пополни — клиенты теряют фото!\n"
                f"https://polza.ai"
            )
    elif level == "warning":
        interval = WARNING_NOTIFY_INTERVAL
        if state["last_level"] not in ("warning", "critical") or (now - state["last_notify_ts"]) >= interval:
            notify_text = (
                f"⚠️ Внимание: баланс Polza.ai = {balance:.2f} ₽\n"
                f"Порог: {WARNING_THRESHOLD:.0f} ₽\n"
                f"Скоро закончится. Пополни заранее.\n"
                f"https://polza.ai"
            )
    else:  # ok
        if state["last_level"] in ("warning", "critical"):
            notify_text = (
                f"✅ Баланс Polza.ai восстановлен: {balance:.2f} ₽"
            )

    if notify_text:
        notify_admins(cfg["vk_token"], cfg["admin_ids"], notify_text)
        state["last_notify_ts"] = now

    state["last_level"] = level
    state["last_balance"] = balance
    save_state(state)


if __name__ == "__main__":
    main()
