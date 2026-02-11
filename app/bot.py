import os
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, Redis
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram.client.session.aiohttp import AiohttpSession

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = '130.49.148.165'
WEBHOOK_PORT = 8443
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}:{WEBHOOK_PORT}{WEBHOOK_PATH}"

# Пути к сертификатам
WEBHOOK_SSL_CERT = "/root/botchattelegram/certs/cert.pem"
WEBHOOK_SSL_PRIV = "/root/botchattelegram/certs/private.key"

# 1. Настройка сессии с расширенными лимитами времени
# Это поможет "пропихнуть" тяжелые файлы через сеть
custom_session = AiohttpSession(
    client_session_props={
        "timeout": aiohttp.ClientTimeout(total=600, connect=30, sock_read=300)
    }
)

# Настройка Redis
redis = Redis(host='localhost', port=6379)
storage = RedisStorage(redis=redis)

# 2. Инициализация бота с новой сессией
bot = Bot(
    token=TOKEN,
    session=custom_session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=storage)

# --- ФУНКЦИИ И ОБРАБОТЧИКИ ---

async def on_startup(bot: Bot):
    # Установка вебхука с сертификатом
    with open(WEBHOOK_SSL_CERT, 'rb') as cert_file:
        await bot.set_webhook(
            url=WEBHOOK_URL,
            certificate=types.BufferedInputFile(cert_file.read(), filename="cert.pem"),
            drop_pending_updates=True
        )
    logging.info(f"🚀 Вебхук установлен на: {WEBHOOK_URL}")

def start_webhook():
    dp.startup.register(on_startup)

    app = web.Application()

    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    # Настройка SSL
    import ssl
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)

    logging.info(f"📡 Запуск веб-сервера на порту {WEBHOOK_PORT}...")
    web.run_app(app, host='0.0.0.0', port=WEBHOOK_PORT, ssl_context=context)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_webhook()