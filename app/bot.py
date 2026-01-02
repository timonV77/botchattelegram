from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from .config import get_settings

settings = get_settings()

# 1. Увеличиваем таймаут до 5 минут (300 секунд)
# Это критически важно для работы с генерацией изображений
session = AiohttpSession()

# 2. Инициализируем бота
# Убираем server=custom_api, так как сервер находится не в РФ и доступ к API прямой
bot = Bot(
    token=settings.bot_token,
    session=session,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML, # HTML менее капризный, чем Markdown
        request_timeout=300        # Добавляем таймаут сюда тоже
    )
)

dp = Dispatcher()