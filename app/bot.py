from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from .config import get_settings

settings = get_settings()

# Мы не создаем TCPConnector здесь вручную, чтобы не вызывать RuntimeError.
# Вместо этого мы настраиваем DefaultBotProperties с большим таймаутом.
# Aiogram сам создаст сессию правильно при запуске.

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        # Это решит проблему ServerDisconnectedError, давая боту 5 минут на отправку
        request_timeout=300
    )
)

# Хранилище для состояний (FSM)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)