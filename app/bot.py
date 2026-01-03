import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from .config import get_settings

settings = get_settings()

# --- ОПТИМИЗАЦИЯ СЕТЕВОГО СОЕДИНЕНИЯ ---
# Создаем кастомный коннектор:
# - keepalive_timeout: как долго держать соединение открытым
# - limit: сколько одновременных соединений (стандартно 100)
connector = aiohttp.TCPConnector(
    keepalive_timeout=60,
    force_close=False,
    enable_cleanup_closed=True
)

# Устанавливаем общие таймауты для aiohttp сессии
# total=None позволяет нам самим задавать таймаут в каждом запросе (request_timeout)
timeout = aiohttp.ClientTimeout(
    total=None,
    connect=30,
    sock_read=300,
    sock_connect=30
)

session = AiohttpSession(
    connector=connector,
    json_loads=None # используем стандартный декодер
)

bot = Bot(
    token=settings.bot_token,
    session=session,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        # Это ВАЖНО: теперь aiogram будет ждать до 5 минут ответа от API Telegram
        request_timeout=300
    )
)

# Хранилище для состояний (FSM)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)