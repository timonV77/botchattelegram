import asyncio
import os
import logging
from aiohttp import web
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Импортируем из твоего проекта
from app.bot import dp, bot
from app.routers import setup_routers
from app.routers.payments import prodamus_webhook


async def main():
    # 1. Настраиваем роутеры
    setup_routers(dp)

    # 2. Настройка веб-сервера платежей
    app = web.Application()
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 8080))

    try:
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"✅ Сервер платежей запущен на порту {port}")
    except OSError:
        print(f"⚠️ Порт {port} уже занят")

    # --- ИСПРАВЛЕНИЕ ТАЙМАУТА ---
    # Мы не создаем сложный объект ClientTimeout, а просто пересоздаем сессию
    # и полагаемся на внутренние механизмы aiogram для длительных запросов.
    if not bot.session or bot.session.closed:
        bot.session = AiohttpSession()

    print("🚀 Запуск бота в режиме Polling...")

    try:
        # Включаем автоматическое управление таймаутами внутри aiogram
        await dp.start_polling(bot, skip_updates=True, request_timeout=300)
    except Exception as e:
        logging.error(f"❌ Критическая ошибка в работе бота: {e}")
    finally:
        if bot.session:
            await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Бот остановлен")