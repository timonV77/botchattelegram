import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, Redis

from app.config import settings

# Инициализация Redis для FSM
redis = Redis(host=settings.redis_host, port=settings.redis_port)
storage = RedisStorage(redis=redis)

# Единый Dispatcher на всё приложение
dp = Dispatcher(storage=storage)
logging.info("DP id in app.bot: %s", id(dp))


def create_bot(session=None) -> Bot:
    """
    Фабрика бота.
    Если session передана — используем её,
    иначе aiogram создаст сессию автоматически.
    """
    if session is not None:
        return Bot(
            token=settings.bot_token,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )

    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )