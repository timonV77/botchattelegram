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
    dp.message.middleware(AlbumMiddleware(latency=0.6))
    setup_routers(dp)
    logging.info("✅ Роутеры и Middleware настроены")

    # 3. Настройка сессии (Твои настройки TLS и IPv4)
    timeout = ClientTimeout(total=600, connect=30, sock_read=300)
    custom_ssl_context = ssl.create_default_context()
    custom_ssl_context.set_ciphers('DEFAULT@SECLEVEL=1')
    custom_ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2
    custom_ssl_context.check_hostname = False
    custom_ssl_context.verify_mode = ssl.CERT_NONE

    session = AiohttpSession(timeout=timeout)
    session._connector = aiohttp.TCPConnector(
        ssl=custom_ssl_context,
        family=socket.AF_INET,
        resolver=aiohttp.ThreadedResolver()
    )
    session.middleware(retry_middleware)
    bot.session = session

    # 4. Очистка вебхука и запуск Polling в фоне
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🗑 Старый вебхук удален, ожидающие сообщения очищены")

    # 5. Настройка сервера для Prodamus (Webhook для платежей)
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    # Настройка SSL для Prodamus
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT, ssl_context=context)
    await site.start()
    logging.info(f"💳 Сервер платежей Prodamus запущен на порту {WEBHOOK_PORT}")

    # 6. ЗАПУСК БОТА (Long Polling)
    logging.info("🚀 Бот запущен в режиме Long Polling!")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"❌ Ошибка при опросе: {e}")
    finally:
        await bot.session.close()
        await runner.cleanup()
        await db.close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Бот остановлен")