import os
from aiogram import Bot

async def get_telegram_photo_url(bot: Bot, file_id: str) -> str:
    file = await bot.get_file(file_id)
    token = os.getenv("BOT_TOKEN")
    return f"https://api.telegram.org/file/bot{token}/{file.file_path}"
