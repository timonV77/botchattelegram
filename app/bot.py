from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from .config import get_settings

settings = get_settings()

# Создаем сессию без передачи коннектора (он создастся сам внутри сессии)
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