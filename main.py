import asyncio
import aiohttp
import os
import logging
import ssl
import socket
from aiohttp import web, ClientTimeout
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

# Импорты из твоего проекта
from app.bot import dp, bot
from app.routers import setup_routers
from app.routers.payments import prodamus_webhook
import database as db
from app.routers.album_middleware import AlbumMiddleware

# --- КОНФИГУРАЦИЯ ---
WEBHOOK_PORT = 8443
WEBHOOK_SSL_CERT = "/root/botchattelegram/certs/cert.pem"
WEBHOOK_SSL_PRIV = "/root/botchattelegram/certs/private.key"


# --- МЕХАНИЗМ ПОВТОРОВ (RETRY) ---
async def retry_middleware(handler, bot, method):
    for attempt in range(1, 4):
        try:
            return await handler(bot, method)
        except (TelegramNetworkError, asyncio.TimeoutError) as e:
            if attempt < 3:
                wait_time = 5 * attempt
                logging.warning(f"⚠️ Ошибка сети (попытка {attempt}/3). Ждем {wait_time}с...")
                await asyncio.sleep(wait_time)
            else:
                raise
        except Exception as e:
            raise


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # 1. База данных
    await db.init_db()

    # 2. Роутеры и Middleware
    setup_routers(dp)
    dp.message.middleware(AlbumMiddleware(latency=0.6))
    logging.info("✅ База и роутеры готовы")

    # 3. Упрощенная сессия (без лишних сложностей, которые могут вешать старт)
    # Используем стандартный коннектор, но с отключенным SSL-верификатором
    connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
    session = AiohttpSession(proxy=None)  # Можно оставить пустым
    session._connector = connector  # Либо настраиваем внутренний атрибут напрямую

    bot.session = session
    logging.info("✅ Сессия создана (SSL OFF)")

    # 4. Запуск сервера для Prodamus в фоне
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    # SSL для платежей (оставляем как было)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT, ssl_context=context)
    await site.start()
    logging.info(f"💳 Prodamus на порту {WEBHOOK_PORT}")

    # 5. СТАРТ БОТА (с принудительным дропом вебхука внутри polling)
    logging.info("🚀 Пробую запустить Polling...")
    try:
        # skip_updates=True заставит бота игнорировать старые сообщения,
        # которые накопились, пока он лежал (это разгрузит сервер на старте)
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logging.error(f"❌ Ошибка в Polling: {e}")
    finally:
        await runner.cleanup()
        await db.close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Бот остановлен")