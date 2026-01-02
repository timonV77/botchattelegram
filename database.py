import os
import logging
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Базовые заголовки
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Единый клиент для всего приложения
client = httpx.AsyncClient(
    base_url=SUPABASE_URL,
    headers=HEADERS,
    timeout=TIMEOUT,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)


async def get_users_count():
    """Возвращает общее количество пользователей (исправлено)."""
    try:
        # Для получения count в Supabase ОБЯЗАТЕЛЕН заголовок Prefer
        count_headers = {**HEADERS, "Prefer": "count=exact"}
        response = await client.get(
            "/rest/v1/users",
            params={"select": "user_id", "limit": 1},
            headers=count_headers
        )
        response.raise_for_status()

        # Данные о количестве приходят в заголовке Content-Range
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            return int(content_range.split("/")[-1])
        return 0
    except Exception as e:
        logging.error(f"❌ Ошибка подсчета пользователей: {e}")
        return 0


async def create_new_user(user_id: int, referrer_id: int = None):
    """Регистрирует нового пользователя."""
    try:
        data = {
            "user_id": int(user_id),
            "balance": 1,
            "referrer_id": int(referrer_id) if referrer_id else None
        }
        # Используем Prefer для возврата созданной записи
        post_headers = {**HEADERS, "Prefer": "return=representation"}
        response = await client.post("/rest/v1/users", json=data, headers=post_headers)

        if response.status_code in [201, 200, 409]:
            logging.info(f"👤 Пользователь {user_id} готов (Ref: {referrer_id})")
            return True
        return False
    except Exception as e:
        logging.error(f"❌ Ошибка создания пользователя {user_id}: {e}")
        return False


async def get_balance(user_id: int):
    """Получает баланс пользователя. Если нет — создаёт."""
    try:
        response = await client.get(
            "/rest/v1/users",
            params={"select": "balance", "user_id": f"eq.{int(user_id)}"}
        )
        response.raise_for_status()
        data = response.json()

        if not data:
            await create_new_user(user_id)
            return 1
        return int(data[0]["balance"])
    except Exception as e:
        logging.error(f"❌ Ошибка get_balance для {user_id}: {e}")
        return 0


async def update_balance(user_id: int, amount: int):
    """Изменяет баланс (инкремент/декремент)."""
    try:
        current = await get_balance(user_id)
        new_balance = max(0, current + amount)
        response = await client.patch(
            "/rest/v1/users",
            params={"user_id": f"eq.{int(user_id)}"},
            json={"balance": new_balance}
        )
        response.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка update_balance для {user_id}: {e}")
        return False


async def set_referrer(user_id: int, referrer_id: int):
    """Устанавливает реферера, если он еще не задан."""
    if int(user_id) == int(referrer_id):
        return
    try:
        response = await client.get(
            "/rest/v1/users",
            params={"select": "referrer_id", "user_id": f"eq.{int(user_id)}"}
        )
        data = response.json()

        if not data:
            await create_new_user(user_id, referrer_id)
        elif data[0].get("referrer_id") is None:
            await client.patch(
                "/rest/v1/users",
                params={"user_id": f"eq.{int(user_id)}"},
                json={"referrer_id": int(referrer_id)}
            )
    except Exception as e:
        logging.error(f"❌ Ошибка set_referrer: {e}")


async def log_payment(user_id: int, amount: int, status: str, order_id: str, raw_data: dict):
    """Логирование платежа."""
    try:
        await client.post("/rest/v1/payment_logs", json={
            "user_id": int(user_id),
            "amount": amount,
            "status": status,
            "order_id": str(order_id),
            "raw_data": raw_data
        })
    except Exception as e:
        logging.error(f"❌ Ошибка log_payment: {e}")


async def get_referrals_count(user_id: int):
    """Количество приглашённых пользователей (исправлено)."""
    try:
        count_headers = {**HEADERS, "Prefer": "count=exact"}
        response = await client.get(
            "/rest/v1/users",
            params={
                "select": "user_id",
                "referrer_id": f"eq.{int(user_id)}",
                "limit": 1
            },
            headers=count_headers
        )
        response.raise_for_status()

        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            return int(content_range.split("/")[-1])
        return 0
    except Exception as e:
        logging.error(f"❌ Ошибка get_referrals_count: {e}")
        return 0