from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, Redis
from app.config import settings

# Инициализация Redis для состояний (FSM)
redis = Redis(host=settings.redis_host, port=settings.redis_port)
storage = RedisStorage(redis=redis)

# Диспетчер создается один раз
dp = Dispatcher(storage=storage)

def create_bot(session):
    """
    Фабрика для создания бота.
    Принимает уже готовую сессию из main.py
    """
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )