from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from app.keyboards.reply import main_kb

router = Router()


@router.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()

    # 1️⃣ СНАЧАЛА приветственный текст
    await message.answer(
        "👋 Привет! Я твой личный AI-фотограф.\n\n"
        "Отправь мне фото, выбери стиль и получи шедевр!",
        reply_markup=main_kb()
    )

    # 2️⃣ СРАЗУ ПОСЛЕ — файл
    await message.answer_document(
        FSInputFile("assets/offer.pdf"),
        caption="📄 Продолжая пользоваться ботом, вы даёте согласие с условиями оферты."
    )
