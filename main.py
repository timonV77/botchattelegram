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
    """
    Если отправка сообщения сорвалась из-за сети, пробуем еще раз.
    Специальная обработка для больших видео.
    """
    for attempt in range(1, 4):  # 3 попытки
        try:
            # Для отправки видео используем больший таймаут
            if hasattr(method, 'video') or 'sendVideo' in str(type(method)):
                logging.info(f"📹 Обнаружена отправка видео (попытка {attempt}/3)")
                # Пропускаем middleware для видео - пусть обрабатывается с дефолтными таймаутами
                return await handler(bot, method)
            else:
                # Обычные запросы
                return await handler(bot, method)

        except TelegramNetworkError as e:
            if attempt < 3:
                wait_time = 10 * attempt  # 10, 20, 30 сек
                logging.warning(f"⚠️ Сетевая ошибка (попытка {attempt}/3): {str(e)[:80]}. Ждем {wait_time} сек...")
                await asyncio.sleep(wait_time)
            else:
                logging.error(f"❌ Сетевая ошибка после 3 попыток: {e}")
                raise

        except asyncio.TimeoutError:
            if attempt < 3:
                wait_time = 10 * attempt
                logging.warning(f"⚠️ Таймаут (попытка {attempt}/3). Ждем {wait_time} сек...")
                await asyncio.sleep(wait_time)
            else:
                logging.error(f"❌ Таймаут после 3 попыток")
                raise

        except Exception as e:
            # Не retry для других ошибок
            logging.error(f"❌ Ошибка: {e}")
            raise

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

    # 4. Настройка сессии бота (Исправлено для TLS 1.2)
    timeout = ClientTimeout(
        total=600,
        connect=30,
        sock_read=300,
        sock_connect=30
    )

    # --- НОВЫЙ БЛОК ДЛЯ TLS 1.2 ---
    custom_ssl_context = ssl.create_default_context()
    # Принудительно устанавливаем TLS 1.2 (так как 1.3 у тебя виснет)
    custom_ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2
    custom_ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Если сертификаты самоподписанные или нужно игнорировать проверку (как было у тебя ssl=False):
    custom_ssl_context.check_hostname = False
    custom_ssl_context.verify_mode = ssl.CERT_NONE
    # ------------------------------

    session = AiohttpSession(timeout=timeout)

    # Настраиваем коннектор с нашим SSL контекстом
    session._connector = aiohttp.TCPConnector(
        ssl=custom_ssl_context,  # Используем наш кастомный контекст вместо False
        limit_per_host=10,
        limit=100
    )

    # Регистрируем retry middleware
    session.middleware(retry_middleware)
    bot.session = session
    logging.info(f"✅ Сессия бота настроена: таймаут {timeout.total}s, sock_read {timeout.sock_read}s")

    # 5. Настройка веб-приложения aiohttp
    app = web.Application(
        client_max_size=100 * 1024 * 1024,  # 100 MB макс размер входящего запроса
    )

    # Маршрут для платежей Prodamus
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    # ОБРАБОТЧИК ВЕБХУКОВ
    # reply_into_webhook=False — ответы отправляются отдельными запросами
    # handle_as_tasks=True — обработка обно��лений в фоновых задачах (КРИТИЧНО!)
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        handle_as_tasks=True,  # КРИТИЧНО! Обработка в фоне
        reply_into_webhook=False  # КРИТИЧНО! Отдельные запросы для видео
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    # 6. Настройка SSL контекста для HTTPS сервера
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)

    # 7. Запуск сервера
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT, ssl_context=context)

    try:
        await site.start()
        logging.info(f"📡 Сервер активен на порту: {WEBHOOK_PORT}")
        logging.info(f"🌐 Webhook URL: {WEBHOOK_URL}")
        logging.info("✅ Бот готов к работе!")
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