import asyncio
import aiohttp
import os
import logging
import ssl
from aiohttp import web, ClientTimeout
from aiogram import types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

# Импорты из твоего проекта
from app.bot import dp, bot
from app.routers import setup_routers
from app.routers.payments import prodamus_webhook
import database as db
from app.routers.album_middleware import AlbumMiddleware

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = '130.49.148.165'
WEBHOOK_PORT = 8443
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}:{WEBHOOK_PORT}{WEBHOOK_PATH}"

WEBHOOK_SSL_CERT = "/root/botchattelegram/certs/cert.pem"
WEBHOOK_SSL_PRIV = "/root/botchattelegram/certs/private.key"


# --- МЕХАНИЗМ ПОВТОРОВ (RETRY) ---
async def retry_middleware(handler, bot, method):
    """Если отправка сообщения сорвалась из-за сети, пробуем еще раз"""
    for attempt in range(3):
        try:
            return await handler(bot, method)
        except TelegramNetworkError as e:
            if attempt == 2: raise e
            logging.warning(f"⚠️ Сетевая ошибка Telegram, попытка {attempt + 1}/3...")
            await asyncio.sleep(1.5)  # Немного увеличили паузу между попытками
    return await handler(bot, method)


async def on_startup(bot):
    logging.info("⚙️ Настройка вебхука...")
    try:
        with open(WEBHOOK_SSL_CERT, 'rb') as cert_file:
            await bot.set_webhook(
                url=WEBHOOK_URL,
                certificate=types.BufferedInputFile(cert_file.read(), filename="cert.pem"),
                drop_pending_updates=True,
                allowed_updates=dp.resolve_used_update_types()
            )
        logging.info(f"🚀 Вебхук успешно установлен: {WEBHOOK_URL}")
    except Exception as e:
        logging.error(f"❌ Ошибка при установке вебхука: {e}")


async def main():
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # 1. Инициализация базы данных
    await db.init_db()

    # 2. РЕГИСТРАЦИЯ MIDDLEWARE
    dp.message.middleware(AlbumMiddleware(latency=0.6))
    logging.info("✅ AlbumMiddleware зарегистрирован")

    # 3. Подключение роутеров
    setup_routers(dp)
    dp.startup.register(on_startup)

    # 4. Настройка сессии бота (Исправлено для тяжелых файлов и SSL)
    # Увеличиваем sock_read до 300 (5 минут), чтобы файлы успевали прогружаться
    timeout = ClientTimeout(total=300, connect=30, sock_read=300, sock_connect=30)
    session = AiohttpSession(timeout=timeout)

    # Прямая подмена коннектора для игнорирования проблемных SSL сертификатов
    session._connector = aiohttp.TCPConnector(ssl=False)

    session.middleware(retry_middleware)
    bot.session = session

    # 5. Настройка веб-приложения aiohttp
    app = web.Application()

    # Маршрут для платежей Prodamus
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    # ОБРАБОТЧИК ВЕБХУКОВ (Критическое изменение!)
    # reply_into_webhook=False заставляет бота слать фото ОТДЕЛЬНЫМ запросом.
    # Это решает проблему 'Connection lost' после долгой генерации.
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        handle_as_tasks=True,
        reply_into_webhook=False
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    # 6. Настройка SSL контекста для HTTPS сервера (входящие от Telegram)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)

    # 7. Запуск сервера
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT, ssl_context=context)

    try:
        await site.start()
        logging.info(f"📡 Сервер активен на порту: {WEBHOOK_PORT}")
        await asyncio.Event().wait()
    except Exception as e:
        logging.error(f"❌ Критическая ошибка сервера: {e}")
    finally:
        # Корректное завершение
        if bot.session:
            await bot.session.close()
        await runner.cleanup()
        await db.close_db()
        logging.info("🛑 Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Принудительная остановка")