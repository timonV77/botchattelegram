import asyncio
import os
import logging
import ssl

# ВАЖНО: конфиг логирования до импортов app.*,
# чтобы видеть логи из app.bot при импорте (например DP id)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

from aiohttp import web
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot import dp, settings
from app.routers import setup_routers
from app.routers.payments import prodamus_webhook
from app.routers.album_middleware import AlbumMiddleware
import database as db

# --- КОНФИГУРАЦИЯ ---
WEBHOOK_PORT = 8443
WEBHOOK_SSL_CERT = "/root/botchattelegram/certs/cert.pem"
WEBHOOK_SSL_PRIV = "/root/botchattelegram/certs/private.key"


async def main():
    # 1. Инициализация базы данных
    await db.init_db()

    # 2. Инициализация бота
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # 3. Роутеры и middleware
    setup_routers(dp)
    logging.info("DP id in main: %s", id(dp))

    # Диагностика: какие типы апдейтов подписаны
    try:
        logging.info("Used update types: %s", dp.resolve_used_update_types())
    except Exception as e:
        logging.warning("resolve_used_update_types failed: %s", e)

    dp.message.middleware(AlbumMiddleware(latency=0.6))
    logging.info("✅ База и роутеры готовы")

    # 4. Сервер webhook для платежей
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app["bot"] = bot
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    runner = web.AppRunner(app)
    await runner.setup()

    if os.path.exists(WEBHOOK_SSL_CERT) and os.path.exists(WEBHOOK_SSL_PRIV):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)
        site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT, ssl_context=context)
    else:
        logging.warning("⚠️ SSL сертификаты не найдены (или неполные). Работаем без SSL.")
        site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)

    await site.start()
    logging.info("💳 Сервер платежей запущен на порту %s", WEBHOOK_PORT)

    # 5. Polling
    logging.info("🚀 Запуск Polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logging.exception("❌ Критическая ошибка в polling: %s", e)
    finally:
        logging.info("♻️ Завершение работы: очистка ресурсов...")
        await runner.cleanup()
        await bot.session.close()
        await db.close_db()
        logging.info("🛑 Процесс завершен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Принудительная остановка")