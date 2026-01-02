import os
import logging
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Создаем единый клиент для всего приложения
# Это защищает от ошибок "Too many open files" и разрывов соединений
client = httpx.AsyncClient(
    base_url=SUPABASE_URL,
    headers=HEADERS,
    timeout=TIMEOUT,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)


async def get_users_count():
    """Возвращает общее количество пользователей."""
    try:
        response = await client.get("/rest/v1/users?select=*", params={"count": "exact"})
        response.raise_for_status()
        # Возвращаем количество из заголовка или длину данных
        count = response.headers.get("Content-Range", "0-0/0").split("/")[-1]
        return int(count)
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
        response = await client.post("/rest/v1/users", json=data)
        if response.status_code in [201, 409]:  # 409 значит уже существует
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
        # Проверяем текущего пользователя
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
    """Логирование платежа в таблицу payment_logs."""
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