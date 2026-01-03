import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage, Redis
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
# Используем твой IP, который ты указал в сертификате
WEBHOOK_HOST = '130.49.148.165'
WEBHOOK_PORT = 8443
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}:{WEBHOOK_PORT}{WEBHOOK_PATH}"

# Пути к сертификатам
WEBHOOK_SSL_CERT = "/root/botchattelegram/certs/cert.pem"
WEBHOOK_SSL_PRIV = "/root/botchattelegram/certs/private.key"

# Настройка Redis
redis = Redis(host='localhost', port=6379)
storage = RedisStorage(redis=redis)

# Инициализация бота
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=storage)


# Функция, которая выполнится при запуске
async def on_startup(bot: Bot):
    # Установка вебхука с передачей нашего самоподписанного сертификата
    with open(WEBHOOK_SSL_CERT, 'rb') as cert_file:
        await bot.set_webhook(
            url=WEBHOOK_URL,
            certificate=types.BufferedInputFile(cert_file.read(), filename="cert.pem"),
            drop_pending_updates=True  # Удалит старые сообщения, скопившиеся в очереди
        )
    logging.info(f"🚀 Вебхук установлен на: {WEBHOOK_URL}")


def start_webhook():
    # Регистрация события старта
    dp.startup.register(on_startup)

    # Создание aiohttp приложения
    app = web.Application()

    # Настройка обработчика запросов
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    # Связываем aiogram с приложением aiohttp
    setup_application(app, dp, bot=bot)

    # Настройка SSL контекста
    import ssl
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)

    # Запуск сервера
    logging.info(f"📡 Запуск веб-сервера на порту {WEBHOOK_PORT}...")
    web.run_app(app, host='0.0.0.0', port=WEBHOOK_PORT, ssl_context=context)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_webhook()