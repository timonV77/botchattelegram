import os
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, Redis
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

# Настройка Redis
try:
    redis = Redis(host='localhost', port=6379, decode_responses=False)
    storage = RedisStorage(redis=redis)
    print("✅ Redis подключен успешно")
except Exception as e:
    print(f"⚠️ Redis не доступен ({e}), использую MemoryStorage")
    storage = MemoryStorage()

# Увеличиваем таймауты для стабильности при больших нагрузках
session = AiohttpSession(
    timeout=aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)
)

bot = Bot(
    token=os.getenv("BOT_TOKEN"),
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=storage)