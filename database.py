import os
import logging
import asyncio
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# Настройки подключения к твоей новой базе
DB_CONFIG = {
    "database": os.getenv("DB_NAME", "bot_db"),
    "user": os.getenv("DB_USER", "bot_user"),
    "password": os.getenv("DB_PASS"),
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 5432))
}

# Пул соединений (создается один раз при запуске)
db_pool = None

async def init_db():
    """Инициализация пула соединений."""
    global db_pool
    if db_pool is None:
        try:
            db_pool = await asyncpg.create_pool(**DB_CONFIG)
            logging.info("✅ Пул соединений с БД успешно создан")
        except Exception as e:
            logging.error(f"❌ Ошибка подключения к локальной БД: {e}")

async def get_users_count():
    """Возвращает общее количество пользователей."""
    await init_db()
    try:
        async with db_pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM users")
            return count or 0
    except Exception as e:
        logging.error(f"❌ Ошибка подсчета пользователей: {e}")
        return 0

async def create_new_user(user_id: int, referrer_id: int = None):
    """Регистрирует нового пользователя."""
    await init_db()
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (user_id, balance, referrer_id) VALUES ($1, 1, $2) ON CONFLICT (user_id) DO NOTHING",
                int(user_id), int(referrer_id) if referrer_id else None
            )
            logging.info(f"👤 Пользователь {user_id} готов (Ref: {referrer_id})")
            return True
    except Exception as e:
        logging.error(f"❌ Ошибка создания пользователя {user_id}: {e}")
        return False

async def get_balance(user_id: int):
    """Получает баланс пользователя. Если нет — создаёт."""
    await init_db()
    try:
        async with db_pool.acquire() as conn:
            balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1", int(user_id))
            if balance is None:
                await create_new_user(user_id)
                return 1
            return balance
    except Exception as e:
        logging.error(f"❌ Ошибка get_balance для {user_id}: {e}")
        return 0

async def update_balance(user_id: int, amount: int):
    """Изменяет баланс (инкремент/декремент)."""
    await init_db()
    try:
        async with db_pool.acquire() as conn:
            # Атомарное обновление прямо в БД — это надежнее и быстрее
            await conn.execute(
                "UPDATE users SET balance = GREATEST(0, balance + $1) WHERE user_id = $2",
                amount, int(user_id)
            )
            return True
    except Exception as e:
        logging.error(f"❌ Ошибка update_balance для {user_id}: {e}")
        return False

async def set_referrer(user_id: int, referrer_id: int):
    """Устанавливает реферера, если он еще не задан."""
    if int(user_id) == int(referrer_id):
        return
    await init_db()
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET referrer_id = $1 WHERE user_id = $2 AND referrer_id IS NULL",
                int(referrer_id), int(user_id)
            )
    except Exception as e:
        logging.error(f"❌ Ошибка set_referrer: {e}")

async def log_payment(user_id: int, amount: int, status: str, order_id: str, raw_data: dict):
    """Логирование платежа."""
    await init_db()
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO payment_logs (user_id, amount, status) VALUES ($1, $2, $3)",
                int(user_id), amount, status
            )
    except Exception as e:
        logging.error(f"❌ Ошибка log_payment: {e}")

async def get_referrals_count(user_id: int):
    """Количество приглашённых пользователей."""
    await init_db()
    try:
        async with db_pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE referrer_id = $1", int(user_id))
            return count or 0
    except Exception as e:
        logging.error(f"❌ Ошибка get_referrals_count: {e}")
        return 0