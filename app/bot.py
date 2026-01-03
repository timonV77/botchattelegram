import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from .config import get_settings

settings = get_settings()

# Специальный коннектор для борьбы с ServerDisconnectedError
connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
session = AiohttpSession(connector=connector)

bot = Bot(
    token=settings.bot_token,
    session=session,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)