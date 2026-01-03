import asyncio
import os
import logging
import ssl
from aiohttp import web, ClientTimeout
from aiogram import types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.client.session.aiohttp import AiohttpSession

# Импортируем из твоего проекта
from app.bot import dp, bot
from app.routers import setup_routers
from app.routers.payments import prodamus_webhook
import database as db

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = '130.49.148.165'
WEBHOOK_PORT = 8443
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}:{WEBHOOK_PORT}{WEBHOOK_PATH}"

# Пути к сертификатам
WEBHOOK_SSL_CERT = "/root/botchattelegram/certs/cert.pem"
WEBHOOK_SSL_PRIV = "/root/botchattelegram/certs/private.key"


async def on_startup(bot):
    """Действия при запуске: установка вебхука"""
    logging.info("⚙️ Настройка вебхука...")
    with open(WEBHOOK_SSL_CERT, 'rb') as cert_file:
        await bot.set_webhook(
            url=WEBHOOK_URL,
            certificate=types.BufferedInputFile(cert_file.read(), filename="cert.pem"),
            drop_pending_updates=True,
            allowed_updates=dp.resolve_used_update_types()
        )
    logging.info(f"🚀 Вебхук успешно установлен: {WEBHOOK_URL}")


async def main():
    # 0. Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # 1. Инициализируем БД
    await db.init_db()
    logging.info("✅ Пул соединений с БД инициализирован")

    # 2. Настраиваем роутеры бота
    setup_routers(dp)
    dp.startup.register(on_startup)

    # 3. Настройка HTTP сессии с увеличенными тайм-аутами для стабильности
    # Это лечит ошибки 'Request timeout error'
    timeout = ClientTimeout(total=60, connect=15, sock_read=15)
    bot.session = AiohttpSession(timeout=timeout)

    # 4. Создание веб-приложения aiohttp
    app = web.Application()

    # Эндпоинт для платежей Prodamus (теперь на порту 8443)
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    # Эндпоинт для Telegram вебхука
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    # Связываем aiogram с приложением
    setup_application(app, dp, bot=bot)

    # 5. Настройка SSL (HTTPS)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)

    # 6. Запуск сервера
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT, ssl_context=context)

    try:
        await site.start()
        logging.info(f"📡 Сервер запущен на порту {WEBHOOK_PORT}")
        logging.info(f"🔗 URL платежей: https://{WEBHOOK_HOST}:{WEBHOOK_PORT}/payments/prodamus")

        # Держим сервис запущенным
        await asyncio.Event().wait()

    except Exception as e:
        logging.error(f"❌ Критическая ошибка при работе сервера: {e}")
    finally:
        logging.info("♻️ Закрытие ресурсов...")
        await bot.session.close()
        await runner.cleanup()
        await db.close_db()
        logging.info("💤 Все соединения закрыты")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Бот остановлен")