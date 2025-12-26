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
    # Проверяем баланс сразу (минимум 1 для обычной бананы)
    if db.get_balance(user_id) < 1:
        return await message.answer("❌ У вас закончились генерации.")

    await message.answer("🖼 Пришлите фотографию, которую хотите изменить:", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_photo)


@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("🤖 Выберите нейросеть для обработки:", reply_markup=model_inline())
    await state.set_state(PhotoProcess.waiting_for_model)


@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    # ИСПРАВЛЕНО: забираем всё, что после "model_", включая "_pro"
    model = callback.data.replace("model_", "")

    await state.update_data(chosen_model=model)

    model_display = model.replace("_", " ").upper()
    await callback.message.edit_text(f"✅ Выбрана модель: **{model_display}**")
    await callback.message.answer(
        "✍️ **Введите описание изменений:**\n"
        "(Например: сделай меня в стиле киберпанк или добавь татуировки)",
        reply_markup=cancel_kb(),
        parse_mode="Markdown"
    )
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

    # Модель теперь корректно сохранится как "nanabanana_pro"
    model = data.get("chosen_model")
    prompt = message.text

    cost = cost_for(model)

    if not has_balance(user_id, cost):
        await state.clear()
        return await message.answer(
            f"❌ Для этой модели нужно {cost} ген. У вас меньше.",
            reply_markup=main_kb()
        )

    status_msg = await message.answer(
        f"⏳ Магия началась... Используем **{model.upper()}**\nЭто может занять до минуты.")

    try:
        photo_url = await get_telegram_photo_url(message.bot, data["photo_id"])
        img_bytes, ext = await generate(photo_url, prompt, model)

        if img_bytes:
            charge(user_id, cost)
            new_balance = db.get_balance(user_id)
            file = BufferedInputFile(img_bytes, filename=f"result.{ext or 'png'}")

            await message.answer_photo(
                photo=file,
                caption=(
                    f"✨ **Результат готов!**\n\n"
                    f"👤 Модель: `{model}`\n"
                    f"📝 Промпт: _{prompt}_\n"
                    f"💰 Списано: {cost} ген.\n"
                    f"🔋 Остаток: {new_balance} ген."
                ),
                reply_markup=main_kb(),
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                "❌ Нейросеть не смогла обработать фото. Попробуйте другой промпт. Баланс не списан.",
                reply_markup=main_kb()
            )
    except Exception as e:
        print(f"Error in on_prompt: {e}")
        await message.answer("❌ Произошла ошибка при обработке. Попробуйте позже.")
    finally:
        await status_msg.delete()
        await state.clear()