from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, Redis
from app.config import settings

# Redis и Storage можно оставить на уровне модуля
redis = Redis(host=settings.redis_host, port=settings.redis_port)
storage = RedisStorage(redis=redis)

dp = Dispatcher(storage=storage)

# Вместо создания бота сразу, создаем функцию-фабрику
def create_bot(session):
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )