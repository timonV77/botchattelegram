import os
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}"
}

TIMEOUT = 10.0  # Таймаут для всех запросов в секундах


async def get_users_count():
    """Возвращает общее количество пользователей."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/users",
                params={"select": "*", "count": "exact"},
                headers=HEADERS
            )
            response.raise_for_status()
            data = response.json()
            return len(data) if data else 0
    except Exception as e:
        logging.error(f"❌ Ошибка Supabase при подсчете пользователей: {e}")
        return 0


async def create_new_user(user_id: int, referrer_id: int = None):
    """Регистрирует нового пользователя, если его нет в базе."""
    try:
        user_id = int(user_id)
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Проверяем, есть ли пользователь
            check = await client.get(
                f"{SUPABASE_URL}/rest/v1/users",
                params={"select": "user_id", "user_id": f"eq.{user_id}"},
                headers=HEADERS
            )
            check.raise_for_status()
            if not check.json():
                data = {
                    "user_id": user_id,
                    "balance": 1,
                    "referrer_id": int(referrer_id) if referrer_id else None
                }
                await client.post(
                    f"{SUPABASE_URL}/rest/v1/users",
                    headers=HEADERS,
                    json=data
                )
                logging.info(f"👤 Новый пользователь {user_id} зарегистрирован (Ref: {referrer_id})")
                return True
        return False
    except Exception as e:
        logging.error(f"❌ Ошибка при создании пользователя {user_id}: {e}")
        return False


async def get_balance(user_id: int):
    """Получает баланс пользователя. Если нет — создаёт его с балансом 1."""
    try:
        user_id = int(user_id)
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/users",
                params={"select": "balance", "user_id": f"eq.{user_id}"},
                headers=HEADERS
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
    """Изменяет баланс пользователя с безопасностью таймаута."""
    try:
        current_balance = await get_balance(user_id)
        new_balance = max(0, current_balance + amount)
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=HEADERS,
                params={"user_id": f"eq.{user_id}"},
                json={"balance": new_balance}
            )
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка update_balance для {user_id}: {e}")
        return False


async def use_generation(user_id: int):
    """Списывает одну генерацию."""
    return await update_balance(user_id, -1)


async def add_balance(user_id: int, count: int):
    """Добавляет баланс пользователю."""
    return await update_balance(user_id, count)


async def log_payment(user_id: int, amount: int, status: str, order_id: str, raw_data: dict):
    """Логирование платежей."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/payment_logs",
                headers=HEADERS,
                json={
                    "user_id": int(user_id),
                    "amount": amount,
                    "status": status,
                    "order_id": order_id,
                    "raw_data": raw_data
                }
            )
    except Exception as e:
        logging.error(f"❌ Ошибка log_payment: {e}")


async def set_referrer(user_id: int, referrer_id: int):
    """Устанавливает пригласившего для нового пользователя."""
    try:
        user_id = int(user_id)
        referrer_id = int(referrer_id)
        if user_id == referrer_id:
            return
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.get(
                f"{SUPABASE_URL}/rest/v1/users",
                params={"select": "user_id,referrer_id", "user_id": f"eq.{user_id}"},
                headers=HEADERS
            )
            res.raise_for_status()
            data = res.json()
            if not data:
                await create_new_user(user_id, referrer_id)
            elif data[0].get("referrer_id") is None:
                await client.patch(
                    f"{SUPABASE_URL}/rest/v1/users",
                    headers=HEADERS,
                    params={"user_id": f"eq.{user_id}"},
                    json={"referrer_id": referrer_id}
                )
    except Exception as e:
        logging.error(f"❌ ОШИБКА set_referrer: {e}")


async def get_referrer(user_id: int):
    """Возвращает ID реферера, если есть."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.get(
                f"{SUPABASE_URL}/rest/v1/users",
                params={"select": "referrer_id", "user_id": f"eq.{user_id}"},
                headers=HEADERS
            )
            res.raise_for_status()
            data = res.json()
            if data and data[0].get("referrer_id"):
                return int(data[0]["referrer_id"])
    except Exception as e:
        logging.error(f"❌ Ошибка get_referrer: {e}")
    return None


async def get_referrals_count(user_id: int):
    """Количество приглашённых пользователей."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.get(
                f"{SUPABASE_URL}/rest/v1/users",
                params={"select": "*", "count": "exact", "referrer_id": f"eq.{user_id}"},
                headers=HEADERS
            )
            res.raise_for_status()
            return res.json().__len__()
    except Exception as e:
        logging.error(f"❌ Ошибка get_referrals_count: {e}")
        return 0
