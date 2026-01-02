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

    # --- ИСПРАВЛЕНИЕ: Удаляем некорректную настройку ---
    # Мы настраиваем ParseMode в app/bot.py, здесь ничего дублировать не нужно

    print("🚀 Запуск бота (Long Polling: 300s timeout)...")

    try:
        # Удаляем вебхук, чтобы не было конфликта с polling
        await bot.delete_webhook(drop_pending_updates=True)

        # ПРАВИЛЬНЫЙ СПОСОБ ЗАДАТЬ ТАЙМАУТ:
        # Передаем request_timeout прямо в start_polling
        await dp.start_polling(
            bot,
            handle_as_tasks=True,
            request_timeout=300
        )
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")
    finally:
        # Корректное закрытие сессий
        if bot.session:
            await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Бот остановлен")