import asyncio
import os
import aiohttp
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
    # --- НАСТРОЙКА ТАЙМАУТОВ ---
    # 300 секунд (5 минут) достаточно для генерации и загрузки тяжелых файлов
    timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=300)

    # Пересоздаем сессию бота с расширенным таймаутом
    # Это решает проблему "TelegramNetworkError: Request timeout error"
    bot.session = AiohttpSession(timeout=timeout)

    # 1. Настраиваем роутеры
    setup_routers(dp)

    # 2. Настройка веб-сервера платежей
    app = web.Application()
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    runner = web.AppRunner(app)
    await runner.setup()

    # Берем порт из переменных окружения или 8080 по умолчанию
    port = int(os.getenv("PORT", 8080))

    try:
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"✅ Сервер платежей запущен на порту {port}")
    except OSError:
        print(f"⚠️ Порт {port} уже занят (возможно, бот запущен в другом процессе)")

    print("🚀 Запуск бота с таймаутом сессии 300с...")

    try:
        # skip_updates=True помогает избежать лавины старых сообщений при перезапуске
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logging.error(f"❌ Критическая ошибка в работе бота: {e}")
    finally:
        # Корректное закрытие ресурсов при остановке службы
        if bot.session:
            await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    # Настраиваем базовое логирование, чтобы видеть события в journalctl
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Бот остановлен пользователем или системой")