from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from app.states import PhotoProcess
from app.keyboards.reply import main_kb, cancel_kb
from app.keyboards.inline import model_inline
from app.services.telegram_file import get_telegram_photo_url
from app.services.generation import cost_for, has_balance, generate, charge
import database as db

router = Router()

@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())

@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if db.get_balance(user_id) < 5:
        return await message.answer("❌ Недостаточно генераций (нужно минимум 5).")
    await message.answer("Пришлите фотографию:", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_photo)

@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("Выберите нейросеть:", reply_markup=model_inline())
    await state.set_state(PhotoProcess.waiting_for_model)

@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model = callback.data.split("_")[1]
    await state.update_data(chosen_model=model)
    await callback.message.edit_text(f"✅ Выбрана модель: **{model.upper()}**.\n\nНапиши промпт:")
    await callback.message.answer("✍️ Введите промпт:", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_prompt)
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def on_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Действие отменено.", reply_markup=main_kb())
    await callback.answer()

@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    if message.text == "❌ Отменить":
        return await cancel_text(message, state)

    user_id = message.from_user.id
    data = await state.get_data()
    model = data["chosen_model"]
    prompt = message.text

    cost = cost_for(model)
    if not has_balance(user_id, cost):
        await state.clear()
        return await message.answer(f"❌ Нужно {cost} ген.", reply_markup=main_kb())

    status_msg = await message.answer(f"🚀 Генерация **{model}**...")

    photo_url = await get_telegram_photo_url(message.bot, data["photo_id"])
    img_bytes, ext = await generate(photo_url, prompt, model)

    if img_bytes:
        charge(user_id, cost)
        new_balance = db.get_balance(user_id)
        file = BufferedInputFile(img_bytes, filename=f"result.{ext or 'png'}")
        await message.answer_photo(
            photo=file,
            caption=f"✅ Готово!\n\nСтиль: {model}\nПромпт: {prompt}\n💰 Остаток: {new_balance} ген.",
            reply_markup=main_kb()
        )
    else:
        await message.answer("❌ Ошибка нейросети. Баланс сохранен.", reply_markup=main_kb())

    await status_msg.delete()
    await state.clear()
