"""
VK Bot — точка входа.
Запуск: python main_vk.py
"""
import logging
import ssl
import aiohttp
from dotenv import load_dotenv

import os
load_dotenv()

# Переопределяем токен Polza только для VK (поскольку TG бот и VK бот используют один и тот же .env файл)
vk_polza_key = os.environ.get("VK_POLZA_API_KEY")
if vk_polza_key:
    os.environ["POLZA_API_KEY"] = vk_polza_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

from vkbottle.bot import Bot
from vkbottle.http import AiohttpClient
from app.config import settings
from app.vk.handlers import VKHandlers
from app.vk.state_manager import VKStateManager
import vk_database as db
from aiohttp import web
from app.vk.payments import prodamus_vk_webhook

# Глобальная переменная бота (заполняется ниже)
bot: Bot = None
runner: web.AppRunner = None


async def on_startup():
    """Запускается внутри event loop — здесь безопасно создавать aiohttp-объекты."""
    global bot

    # Пересоздаём http-клиент с отключённым SSL уже внутри loop
    if settings.vk_disable_ssl_verify:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        session = aiohttp.ClientSession(connector=connector)
        # Правильный атрибут: bot.api.http_client (AiohttpClient)
        bot.api.http_client._session_params = {}
        bot.api.http_client.session = session
        logging.warning("⚠️ SSL-проверка отключена (VK_DISABLE_SSL_VERIFY=1)")

    # Инициализация БД
    try:
        await db.init_db()
        logging.info("✅ VK БД готова")
    except Exception as e:
        logging.error(f"❌ Ошибка инициализации VK БД: {e}")
        raise

    # Запуск сервера вебхуков для Продамуса
    # ВАЖНО: Fly.io открывает наружу только PORT (8080).
    # VK_WEBHOOK_PORT используется локально, но на проде берём PORT из среды.
    global runner
    try:
        webhook_port = int(os.environ.get("PORT", settings.vk_webhook_port))
        app = web.Application(client_max_size=100 * 1024 * 1024)
        app["bot"] = bot
        # Путь /vk/payments/prodamus — уникальный, не конфликтует с TG ботом
        app.router.add_post("/vk/payments/prodamus", prodamus_vk_webhook)
        # Для обратной совместимости также слушаем старый путь
        app.router.add_post("/payments/prodamus", prodamus_vk_webhook)

        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, "0.0.0.0", webhook_port)
        await site.start()
        logging.info(f"💳 Сервер платежей VK запущен на порту {webhook_port}")
        logging.info(f"📌 VK Webhook URL: https://neuro-photo-bot.fly.dev/vk/payments/prodamus")
        logging.info(f"📌 VK Webhook URL (alt): https://neuro-photo-bot.fly.dev/payments/prodamus")
    except Exception as e:
        logging.error(f"❌ Ошибка запуска вебхука VK: {e}")


async def on_shutdown():
    """Закрытие aiohttp-сессии и БД."""
    if settings.vk_disable_ssl_verify and bot:
        http = bot.api.http_client
        if http.session and not http.session.closed:
            await http.session.close()
    if runner:
        await runner.cleanup()
    await db.close_db()
    logging.info("🛑 VK бот остановлен, БД закрыта")


if __name__ == "__main__":
    try:
        if not settings.vk_token:
            raise RuntimeError("❌ VK_TOKEN не задан в .env")

        # 1. Создаём бота (без SSL-настроек — они будут применены в on_startup)
        bot = Bot(token=settings.vk_token)

        # 2. In-memory state manager
        class _FakeRedis:
            async def get(self, *a, **kw):    raise ConnectionError("no redis")
            async def set(self, *a, **kw):    raise ConnectionError("no redis")
            async def delete(self, *a, **kw): raise ConnectionError("no redis")

        state_manager = VKStateManager(redis=_FakeRedis())
        state_manager._redis_available = False
        logging.info("✅ VK State: in-memory режим")

        # 3. Регистрируем хэндлеры
        VKHandlers(bot=bot, state_manager=state_manager)
        logging.info("✅ VK хэндлеры зарегистрированы")

        # 4. on_startup / on_shutdown (корутины, добавляются в список)
        bot.loop_wrapper.on_startup.append(on_startup())
        bot.loop_wrapper.on_shutdown.append(on_shutdown())

        # 5. Запуск (loop_wrapper создаёт event loop, запускает on_startup, затем polling)
        logging.info("🚀 VK бот запускается (long-poll)...")
        bot.run_forever()

    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Принудительная остановка VK бота")
    except Exception as e:
        logging.exception(f"❌ Фатальная ошибка: {e}")
