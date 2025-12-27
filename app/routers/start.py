from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from app.keyboards.reply import main_kb
import database as db  # Импортируем базу данных

router = Router()

@router.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    # --- ЛОГИКА РЕФЕРАЛЬНОЙ ССЫЛКИ ---
    # Получаем аргументы команды /start (все, что идет после пробела)
    args = message.text.split()
    if len(args) > 1:
        referrer_id_str = args[1]
        # Проверяем, что это число и что пользователь не пригласил сам себя
        if referrer_id_str.isdigit():
            referrer_id = int(referrer_id_str)
            if referrer_id != user_id:
                # Записываем реферера в базу (функцию добавим в database.py ниже)
                db.set_referrer(user_id, referrer_id)

    # 1️⃣ Приветственный текст
    await message.answer(
        "👋 Привет! Я твой личный AI-фотограф.\n\n"
        "Отправь мне фото, выбери стиль и получи шедевр!",
        reply_markup=main_kb()
    )

    # 2️⃣ Файл оферты
    await message.answer_document(
        FSInputFile("assets/offer.pdf"),
        caption="📄 Продолжая пользоваться ботом, вы даёте согласие с условиями оферты."
    )