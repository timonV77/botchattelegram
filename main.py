import asyncio
from app.bot import bot, dp
from app.routers import setup_routers

async def main():
    setup_routers(dp)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
