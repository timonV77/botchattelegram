import asyncio
from aiohttp import web
from app.bot import bot, dp
from app.routers import setup_routers
# Импортируем вебхук из вашего нового роутера платежей
from app.routers.payments import prodamus_webhook


async def main():
    # 1. Настраиваем роутеры бота
    setup_routers(dp)

    # 2. Создаем веб-сервер для приема уведомлений от Продамуса
    app = web.Application()
    # Этот путь вы пропишете в кабинете Продамуса
    app.router.add_post("/payments/prodamus", prodamus_webhook)

    # Настраиваем запуск сервера
    runner = web.AppRunner(app)
    await runner.setup()

    # Railway обычно дает порт 8080, если нет — берем из переменной окружения
    import os
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)

    # 3. Запускаем сервер и бота параллельно
    await site.start()
    print(f"✅ Сервер платежей запущен на порту {port}")

    print("🚀 Бот запущен в режиме polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Бот остановлен")