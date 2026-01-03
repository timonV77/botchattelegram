from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import ClientTimeout
from .config import get_settings

settings = get_settings()

# Оптимизируем сессию.
# Мы убираем ClientTimeout отсюда, чтобы aiogram мог сам управлять
# таймаутами через параметр request_timeout в методах или polling.
session = AiohttpSession()

bot = Bot(
    token=settings.bot_token,
    session=session,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

# Хранилище для состояний (FSM)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)