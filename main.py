import asyncio
import os
import logging
from aiohttp import web

# Импортируем из твоего проекта
from app.bot import dp, bot
from app.routers import setup_routers
from app.routers.payments import prodamus_webhook
import database as db  # Импортируем нашу новую базу

async def main():
    # 0. Инициализируем пул соединений с PostgreSQL
    # Это гарантирует мгновенные ответы бота с первой секунды
    await db.init_db()
    logging.info("✅ Пул соединений с БД инициализирован")

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
        print(f"⚠️ Порт {port} уже занят. Если бот перезапустился — это нормально.")

    print("🚀 Запуск бота (Long Polling: 300s timeout)...")

    try:
        # Удаляем вебхук и сбрасываем старые сообщения (drop_pending_updates=True)
        # Это предотвратит "зависание" бота на старых запросах при старте
        await bot.delete_webhook(drop_pending_updates=True)

        await dp.start_polling(
            bot,
            handle_as_tasks=True,
            request_timeout=300
        )
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")
    finally:
        # 3. КОРРЕКТНОЕ ЗАКРЫТИЕ
        logging.info("♻️ Закрытие ресурсов...")
        if bot.session:
            await bot.session.close()
        await runner.cleanup()
        # Закрываем пул соединений с БД, чтобы не «вешать» PostgreSQL
        await db.close_db()
        logging.info("💤 Все соединения закрыты")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Бот остановлен пользователем")