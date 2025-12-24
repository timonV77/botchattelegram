from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from app.keyboards.reply import main_kb

router = Router()

@router.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я твой личный AI-фотограф.\n\n"
        "Отправь мне фото, выбери стиль и получи шедевр!",
        reply_markup=main_kb()
    )
    await message.answer(text, reply_markup=main_kb())

    file = FSInputFile("assets/offer.pdf")
    await message.answer_document(file, caption="Продолжая пользоваться ботом, вы даете свое согласие с условиями данной оферты.")