from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, Redis
from aiogram.client.session.aiohttp import AiohttpSession

from app.config import settings # Импортируем наш конфиг
from app.network import get_connector

# Redis через конфиг
redis = Redis(host=settings.redis_host, port=settings.redis_port)
storage = RedisStorage(redis=redis)

session = AiohttpSession(connector=get_connector())

bot = Bot(
    token=settings.bot_token, # Из конфига
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=storage)