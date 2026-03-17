from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.database import get_users_count

router = Router()

@router.message(Command("users"))
async def cmd_users(message: Message):
    count = await get_users_count()
    await message.answer(f"👥 Пользователей в базе: {count}")