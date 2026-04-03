"""VK Database — PostgreSQL, отдельная БД (VK_DB_*)"""
import os
import logging
import asyncio
import asyncpg
from dotenv import load_dotenv

load_dotenv()

VK_DB_CONFIG = {
    "database": os.getenv("VK_DB_NAME", "bot_vk_db"),
    "user":     os.getenv("VK_DB_USER", "bot_vk_user"),
    "password": os.getenv("VK_DB_PASS"),
    "host":     os.getenv("VK_DB_HOST", "127.0.0.1"),
    "port":     int(os.getenv("VK_DB_PORT", 5432)),
}

_pool = None
_lock = asyncio.Lock()


async def init_db():
    """Инициализация пула соединений + создание таблицы если нет."""
    global _pool
    if _pool is None:
        async with _lock:
            if _pool is None:
                try:
                    _pool = await asyncpg.create_pool(
                        **VK_DB_CONFIG,
                        min_size=2,
                        max_size=10
                    )
                    logging.info("✅ VK DB: пул соединений создан")
                except Exception as e:
                    logging.error(f"❌ VK DB: ошибка подключения: {e}")
                    raise

    # Создаём таблицу при первом запуске
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     BIGINT PRIMARY KEY,
                balance     INTEGER NOT NULL DEFAULT 17,
                referrer_id BIGINT DEFAULT NULL,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        # Проверяем и добавляем referrer_id если таблица уже есть
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT DEFAULT NULL")
        except: pass

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_logs (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT NOT NULL,
                amount     INTEGER NOT NULL,
                status     TEXT NOT NULL,
                order_id   TEXT,
                raw_data   JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Проверяем новые колонки в логах
        try:
            await conn.execute("ALTER TABLE payment_logs ADD COLUMN IF NOT EXISTS order_id TEXT")
            await conn.execute("ALTER TABLE payment_logs ADD COLUMN IF NOT EXISTS raw_data JSONB")
        except: pass


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        logging.info("💤 VK DB: пул соединений закрыт")


async def create_new_user(user_id: int, referrer_id: int = None) -> bool:
    """Регистрируем VK-пользователя (стартовый баланс = 17)."""
    await init_db()
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (user_id, balance, referrer_id) VALUES ($1, 17, $2) "
                "ON CONFLICT (user_id) DO NOTHING",
                int(user_id), referrer_id
            )
        return True
    except Exception as e:
        logging.error(f"❌ VK DB create_new_user {user_id}: {e}")
        return False


async def get_referrer(user_id: int) -> int:
    """Возвращает ID того, кто пригласил этого пользователя."""
    await init_db()
    try:
        async with _pool.acquire() as conn:
            return await conn.fetchval("SELECT referrer_id FROM users WHERE user_id = $1", int(user_id))
    except Exception as e:
        logging.error(f"❌ VK DB get_referrer {user_id}: {e}")
        return None


async def set_referrer(user_id: int, referrer_id: int) -> bool:
    """Устанавливает реферера для пользователя (если еще не установлен)."""
    await init_db()
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET referrer_id = $1 WHERE user_id = $2 AND referrer_id IS NULL",
                int(referrer_id), int(user_id)
            )
        return True
    except Exception as e:
        logging.error(f"❌ VK DB set_referrer {user_id}: {e}")
        return False


async def get_balance(user_id: int) -> int:
    """Возвращает баланс VK-пользователя."""
    await init_db()
    try:
        async with _pool.acquire() as conn:
            balance = await conn.fetchval(
                "SELECT balance FROM users WHERE user_id = $1", int(user_id)
            )
            if balance is None:
                logging.warning(f"⚠️ [DB] get_balance: user {user_id} НЕ НАЙДЕН в таблице users — создаём с балансом 17")
                await create_new_user(user_id)
                return 17
            logging.debug(f"[DB] get_balance: user {user_id} → {balance} руб.")
            return int(balance)
    except Exception as e:
        logging.error(f"❌ VK DB get_balance {user_id}: {e}", exc_info=True)
        return 0


async def update_balance(user_id: int, amount: int) -> bool:
    """Изменяет баланс на amount (может быть отрицательным)."""
    await init_db()
    logging.info(f"[DB] update_balance НАЧАЛО: user={user_id}, delta={amount:+d}")
    try:
        async with _pool.acquire() as conn:
            # Читаем баланс ДО изменения
            balance_before = await conn.fetchval(
                "SELECT balance FROM users WHERE user_id = $1", int(user_id)
            )
            if balance_before is None:
                logging.error(
                    f"❌ [DB] update_balance: user {user_id} НЕ СУЩЕСТВУЕТ в таблице users! "
                    f"UPDATE не будет применён. Нужно сначала создать пользователя."
                )
                return False

            # Выполняем обновление и получаем новый баланс
            row = await conn.fetchrow(
                "UPDATE users SET balance = GREATEST(0, balance + $1) WHERE user_id = $2 "
                "RETURNING balance",
                int(amount), int(user_id)
            )

            if row is None:
                logging.error(
                    f"❌ [DB] update_balance: UPDATE вернул 0 строк для user {user_id}! "
                    f"Баланс НЕ ИЗМЕНЁН."
                )
                return False

            balance_after = row["balance"]
            logging.info(
                f"✅ [DB] update_balance OK: user={user_id}, "
                f"до={balance_before} руб., delta={amount:+d}, после={balance_after} руб."
            )
        return True
    except Exception as e:
        logging.error(f"❌ VK DB update_balance {user_id}: {e}", exc_info=True)
        return False


async def get_users_count() -> int:
    await init_db()
    async with _pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users") or 0


async def get_all_user_ids() -> list:
    await init_db()
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row["user_id"] for row in rows]


async def log_payment(user_id: int, amount: int, status: str, order_id: str = None, raw_data: dict = None) -> None:
    await init_db()
    logging.info(f"[DB] log_payment: user={user_id}, amount={amount}, status={status}, order_id={order_id}")
    try:
        import json
        raw_json = json.dumps(raw_data, ensure_ascii=False) if raw_data else None
        async with _pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO payment_logs (user_id, amount, status, order_id, raw_data) VALUES ($1, $2, $3, $4, $5::jsonb)",
                int(user_id), int(amount), str(status), order_id, raw_json
            )
        logging.info(f"✅ [DB] log_payment записан: user={user_id}, order={order_id}")
    except Exception as e:
        logging.error(f"❌ VK DB log_payment: {e}", exc_info=True)
