import asyncio
import os
import logging
import ssl

from aiohttp import web
from aiogram import Bot # Импортируем Bot напрямую
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot import dp, settings # Добавь импорт settings из твоего конфига
from app.routers import setup_routers
from app.routers.payments import prodamus_webhook
import database as db
from app.routers.album_middleware import AlbumMiddleware

# --- КОНФИГУРАЦИЯ ---
WEBHOOK_PORT = 8443
WEBHOOK_SSL_CERT = "/root/botchattelegram/certs/cert.pem"
WEBHOOK_SSL_PRIV = "/root/botchattelegram/certs/private.key"

async def main():
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # 1. Инициализация базы данных
    await db.init_db()

    # 2. Инициализация Бота (Самый простой и стабильный способ)
    # aiogram сам создаст AiohttpSession внутри
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # 3. Настройка роутеров и Middleware
    setup_routers(dp)
    dp.message.middleware(AlbumMiddleware(latency=0.6))
    logging.info("✅ База и роутеры готовы")

    # 4. Запуск сервера для Prodamus
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app['bot'] = bot # Критически важно для payments.py
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    runner = web.AppRunner(app)
    await runner.setup()

    if os.path.exists(WEBHOOK_SSL_CERT):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)
        site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT, ssl_context=context)
    else:
        logging.warning("⚠️ SSL сертификаты не найдены! Работаем без SSL.")
        site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)

    await site.start()
    logging.info(f"💳 Сервер платежей запущен на порту {WEBHOOK_PORT}")

    # 5. СТАРТ БОТА
    logging.info("🚀 Запуск Polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")
    finally:
        logging.info("♻️ Завершение работы: очистка ресурсов...")
        await runner.cleanup()
        # Закрываем сессию бота
        await bot.session.close()
        await db.close_db()
        logging.info("🛑 Процесс завершен")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Принудительная остановка")