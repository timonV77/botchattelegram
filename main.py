import asyncio
import os
import aiohttp
from aiohttp import web
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode

# Импортируем из твоих файлов
from app.bot import dp, bot
from app.routers import setup_routers
from app.routers.payments import prodamus_webhook


async def main():
    # --- НАСТРОЙКА ТАЙМАУТОВ ---
    # Увеличиваем таймаут до 5 минут (300 секунд).
    # Этого хватит, чтобы отправить даже очень тяжелые фото и видео.
    timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=300)

    # Обновляем сессию бота с новым таймаутом
    if bot.session and not bot.session.closed:
        await bot.session.close()  # Закрываем старую сессию, если она была

    # Создаем новую сессию с расширенными лимитами
    new_session = AiohttpSession(timeout=timeout)
    bot.session = new_session

    # 1. Настраиваем роутеры бота
    setup_routers(dp)

    # 2. Настройка веб-сервера для платежей
    app = web.Application()
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    runner = web.AppRunner(app)
    await runner.setup()

    # Порт для сервера (по умолчанию 8080)
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)

    # 3. Запуск сервера платежей
    await site.start()
    print(f"✅ Сервер платежей запущен на порту {port}")
    print("🚀 Попытка запуска бота с таймаутом 300с...")

    try:
        # Запускаем polling. skip_updates=True пропустит старые сообщения,
        # чтобы бот не захлебнулся после перезапуска.
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        print(f"❌ Критическая ошибка при работе бота: {e}")
    finally:
        # Корректное закрытие всех соединений
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Бот и сервер остановлены")