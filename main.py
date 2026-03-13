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
                # Специальный таймаут для видео (10 минут)
                timeout = ClientTimeout(total=600, connect=30, sock_read=120, sock_connect=30)
                old_timeout = bot.session.timeout
                bot.session.timeout = timeout
                try:
                    result = await handler(bot, method)
                    return result
                finally:
                    bot.session.timeout = old_timeout
            else:
                # Обычный таймаут для остального (5 минут)
                return await handler(bot, method)

        except TelegramNetworkError as e:
            if attempt < 3:
                wait_time = 10 * attempt  # 10, 20, 30 сек
                logging.warning(f"⚠️ Сетевая ошибка Telegram (попытка {attempt}/3): {e}. Ждем {wait_time} сек...")
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
            logging.error(f"❌ Неожиданная ошибка: {e}")
            raise

    # Финальная попытка
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

    # 4. Настройка сессии бота (для больших видео)
    # Увеличиваем sock_read до 300 (5 минут) для больших файлов
    # total=600 (10 минут) — общий таймаут
    timeout = ClientTimeout(
        total=600,  # 10 минут общий таймаут
        connect=30,  # 30 сек на подключение
        sock_read=300,  # 5 минут на чтение
        sock_connect=30  # 30 сек на подключение сокета
    )
    session = AiohttpSession(timeout=timeout)

    # Коннектор без SSL проверки (для самоподписанных сертификатов)
    session._connector = aiohttp.TCPConnector(ssl=False)

    # Регистрируем retry middleware
    session.middleware(retry_middleware)
    bot.session = session

    logging.info(f"✅ Сессия бота настроена: таймаут {timeout.total}s, sock_read {timeout.sock_read}s")

    # 5. Настройка веб-приложения aiohttp
    app = web.Application()

    # Маршрут для платежей Prodamus
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    # ОБРАБОТЧИК ВЕБХУКОВ
    # reply_into_webhook=False — ответы отправляются отдельными запросами (критично для больших видео)
    # handle_as_tasks=True — обработка обновлений в фоновых задачах
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        handle_as_tasks=True,
        reply_into_webhook=False  # КРИТИЧНО! Отправляет видео отдельным запросом
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