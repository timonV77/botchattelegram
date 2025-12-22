from aiogram import Router, types, F
import database as db

router = Router()

@router.message(F.text == "👤 Мой баланс")
async def balance(message: types.Message):
    bal = db.get_balance(message.from_user.id)
    await message.answer(f"💰 Ваш баланс: **{bal}** генераций.")
