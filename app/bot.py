from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from .config import get_settings

settings = get_settings()

# 1. Настраиваем чистую сессию с таймаутом 60 секунд.
# Этого достаточно для стабильной работы на зарубежных хостингах вроде Railway.
session = AiohttpSession(
    timeout=60
)

# 2. Инициализируем бота без прокси
bot = Bot(
    token=settings.bot_token,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)

dp = Dispatcher()