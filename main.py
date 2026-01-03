import asyncio
import os
import logging
import ssl
from aiohttp import web
from aiogram import types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# Импортируем из твоего проекта
from app.bot import dp, bot
from app.routers import setup_routers
from app.routers.payments import prodamus_webhook
import database as db

# Настройки Webhook
WEBHOOK_HOST = '130.49.148.165'
WEBHOOK_PORT = 8443
WEBHOOK_PATH = f"/webhook/{os.getenv('BOT_TOKEN')}"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}:{WEBHOOK_PORT}{WEBHOOK_PATH}"

# Пути к сертификатам
WEBHOOK_SSL_CERT = "/root/botchattelegram/certs/cert.pem"
WEBHOOK_SSL_PRIV = "/root/botchattelegram/certs/private.key"


async def on_startup(bot):
    # Установка вебхука с сертификатом
    with open(WEBHOOK_SSL_CERT, 'rb') as cert_file:
        await bot.set_webhook(
            url=WEBHOOK_URL,
            certificate=types.BufferedInputFile(cert_file.read(), filename="cert.pem"),
            drop_pending_updates=True
        )
    logging.info(f"🚀 Вебхук установлен: {WEBHOOK_URL}")


async def main():
    # 0. Инициализируем БД
    await db.init_db()
    logging.info("✅ Пул соединений с БД инициализирован")

    # 1. Настраиваем роутеры
    setup_routers(dp)
    dp.startup.register(on_startup)

    # 2. Настройка единого веб-приложения
    app = web.Application()

    # Эндпоинт для платежей (порт 8443 теперь будет общим для всего)
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    # Эндпоинт для Telegram
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    # 3. Настройка SSL для порта 8443
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)

    runner = web.AppRunner(app)
    await runner.setup()

    # Запускаем всё на порту 8443 (и платежи, и бота)
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT, ssl_context=context)

    try:
        await site.start()
        logging.info(f"📡 Сервер (Бот + Платежи) запущен на порту {WEBHOOK_PORT}")

        # Бесконечный цикл, чтобы бот не завершался
        await asyncio.Event().wait()

    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")
    finally:
        logging.info("♻️ Закрытие ресурсов...")
        await runner.cleanup()
        await db.close_db()
        logging.info("💤 Все соединения закрыты")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Бот остановлен")