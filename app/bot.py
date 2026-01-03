from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import ClientTimeout
from .config import get_settings

settings = get_settings()

# Настраиваем таймауты: 30 секунд на подключение, 60 на чтение.
# Это предотвратит "бесконечное" ожидание запросов.
session = AiohttpSession(
    timeout=ClientTimeout(total=60, connect=30)
)

bot = Bot(
    token=settings.bot_token,
    session=session,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

# Добавляем MemoryStorage для работы состояний (FSM)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)