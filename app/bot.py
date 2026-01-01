from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer  # Добавили импорт
from .config import get_settings

settings = get_settings()

# 1. Настраиваем сессию с хорошим таймаутом
session = AiohttpSession(
    timeout=60
)

# 2. Настраиваем зеркало API (для обхода таймаутов в РФ)
# Это перенаправит запросы через рабочий узел
custom_api = TelegramAPIServer.from_base("https://api.tgproxy.me")

# 3. Инициализируем бота с использованием сервера-зеркала
bot = Bot(
    token=settings.bot_token,
    session=session,
    server=custom_api,  # Указываем зеркало здесь
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)

dp = Dispatcher()