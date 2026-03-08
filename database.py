import os
import logging
import asyncio
import asyncpg
import json
from dotenv import load_dotenv

load_dotenv()

# Настройки подключения
DB_CONFIG = {
    "database": os.getenv("DB_NAME", "bot_db"),
    "user": os.getenv("DB_USER", "bot_user"),
    "password": os.getenv("DB_PASS"),
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 5432))
}

db_pool = None
db_lock = asyncio.Lock()

async def init_db():
    """Инициализация пула соединений с защитой от двойного создания."""
    global db_pool
    if db_pool is None:
        async with db_lock:
            if db_pool is None:
                try:
                    db_pool = await asyncpg.create_pool(
                        **DB_CONFIG,
                        min_size=5,
                        max_size=20
                    )
                    logging.info("✅ Пул соединений с локальной БД создан")
                except Exception as e:
                    logging.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА БД: {e}")
                    raise e

async def close_db():
    """Закрытие пула при остановке бота."""
    global db_pool
    if db_pool:
        await db_pool.close()
        logging.info("💤 Пул соединений с БД закрыт")

async def get_users_count():
    await init_db()
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users") or 0

async def create_new_user(user_id: int, referrer_id: int = None):
    await init_db()
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (user_id, balance, referrer_id) VALUES ($1, 1, $2) ON CONFLICT (user_id) DO NOTHING",
                int(user_id), int(referrer_id) if referrer_id else None
            )
            return True
    except Exception as e:
        logging.error(f"❌ Ошибка create_new_user {user_id}: {e}")
        return False

async def get_balance(user_id: int):
    await init_db()
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM users WHERE user_id = $1", int(user_id))
        if balance is None:
            await create_new_user(user_id)
            return 1
        return int(balance)

async def update_balance(user_id: int, amount: int):
    await init_db()
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET balance = GREATEST(0, balance + $1) WHERE user_id = $2",
            int(amount), int(user_id)
        )
        return True

async def get_referrer(user_id: int):
    """Возвращает ID того, кто пригласил данного пользователя (нужно для платежей)"""
    await init_db()
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT referrer_id FROM users WHERE user_id = $1", int(user_id))

async def log_payment(user_id: int, amount: int, status: str, order_id: str = None, raw_data: dict = None):
    await init_db()
    try:
        # Превращаем raw_data в строку JSON для хранения в БД, если нужно
        raw_json = json.dumps(raw_data) if raw_data else None
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO payment_logs (user_id, amount, status) VALUES ($1, $2, $3)",
                int(user_id), int(amount), str(status)
            )
    except Exception as e:
        logging.error(f"❌ Ошибка log_payment: {e}")

async def get_referrals_count(user_id: int):
    await init_db()
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE referrer_id = $1", int(user_id)) or 0

async def get_all_user_ids():
    """Возвращает список всех user_id из базы."""
    await init_db()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row["user_id"] for row in rows]