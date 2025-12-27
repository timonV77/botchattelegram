from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from app.keyboards.reply import main_kb
import database as db

router = Router()

@router.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    # 1. Сначала обрабатываем глубокую ссылку (deep-linking)
    args = message.text.split()
    if len(args) > 1:
        payload = args[1]
        if payload.isdigit():
            referrer_id = int(payload)
            # ВАЖНО: Сначала записываем связь в базу
            db.set_referrer(user_id, referrer_id)

    # 2. Теперь инициализируем пользователя (даем баланс, если новый)
    db.get_balance(user_id)

    # 3. Приветствие
    await message.answer(
        "👋 Привет! Я твой личный AI-фотограф.\n\n"
        "Отправь мне фото, выбери стиль и получи шедевр!",
        reply_markup=main_kb()
    )

    # 4. Оферта
    try:
        await message.answer_document(
            FSInputFile("assets/offer.pdf"),
            caption="📄 Продолжая пользоваться ботом, вы даёте согласие с условиями оферты."
        )
    except:
        pass