from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from app.states import PhotoProcess
from app.keyboards.reply import main_kb, cancel_kb
from app.keyboards.inline import model_inline
from app.services.telegram_file import get_telegram_photo_url
from app.services.generation import cost_for, has_balance, generate, charge, generate_video
import database as db

router = Router()

MODEL_NAMES = {
    "nanabanana": "🍌 NanoBanana",
    "nanabanana_pro": "💎 NanoBanana PRO",
    "seadream": "🌊 SeaDream 4.5"
}


# --- ИСПРАВЛЕННЫЙ ХЕНДЛЕР ОТМЕНЫ (теперь ловит везде) ---
@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    """Отмена любого действия в любом состоянии"""
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


# ---------------- СЛУЖЕБНЫЕ КОМАНДЫ ----------------

@router.message(Command("counters"))
async def show_counters(message: types.Message):
    try:
        count = await db.get_users_count()
        await message.answer(
            f"📊 **Статистика бота**\n\n"
            f"👤 Всего зарегистрировано: `{count}` пользователей.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer("❌ Не удалось получить статистику.")


# ---------------- ФОТОСЕССИЯ ----------------

@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    balance = await db.get_balance(user_id)

    if balance < 1:
        return await message.answer("❌ У вас недостаточно генераций.", reply_markup=main_kb())

    await message.answer(
        "🖼 **Пришлите фотографию**, которую хотите изменить:",
        reply_markup=cancel_kb(),
        parse_mode="Markdown"
    )
    await state.set_state(PhotoProcess.waiting_for_photo)


@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer(
        "🤖 **Выберите нейросеть для обработки:**",
        reply_markup=model_inline(),
        parse_mode="Markdown"
    )
    await state.set_state(PhotoProcess.waiting_for_model)


@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")
    await state.update_data(chosen_model=model_key)
    nice_name = MODEL_NAMES.get(model_key, model_key)

    await callback.message.edit_text(f"🎯 **Выбрана модель:** {nice_name}", parse_mode="Markdown")
    await callback.message.answer(
        "✍️ **Опишите, что нужно изменить на фото:**",
        reply_markup=cancel_kb(),
        parse_mode="Markdown"
    )
    await state.set_state(PhotoProcess.waiting_for_prompt)
    await callback.answer()


@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    # Убираем ручную проверку 'Отменить', так как теперь есть глобальный хендлер выше
    if not message.text:
        return await message.answer("✍️ Пожалуйста, введите текстовое описание.")

    user_prompt = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()

    model = data.get("chosen_model", "nanabanana")

    # Исправлен вызов: передаем ключ модели, generation.py сам определит стоимость
    if not await has_balance(user_id, model):
        await state.clear()
        return await message.answer("❌ Недостаточно средств.", reply_markup=main_kb())

    nice_name = MODEL_NAMES.get(model, model)
    status_msg = await message.answer(f"🚀 **Генерирую изображение ({nice_name})...**", parse_mode="Markdown")

    try:
        photo_url = await get_telegram_photo_url(message.bot, data["photo_id"])
        img_bytes, ext = await generate(photo_url, user_prompt, model)

        if not img_bytes:
            await message.answer("❌ Ошибка нейросети. Попробуйте еще раз.", reply_markup=main_kb())
            return

        await charge(user_id, model)
        current_balance = await db.get_balance(user_id)

        file = BufferedInputFile(img_bytes, filename=f"result.{ext or 'png'}")
        await message.answer_photo(
            photo=file,
            caption=f"✨ **Готово!**\n\nБаланс: `{current_balance}` ⚡",
            reply_markup=main_kb(),
            parse_mode="Markdown"
        )
        await state.clear()
    except Exception as e:
        await message.answer("❌ Ошибка при генерации.", reply_markup=main_kb())
    finally:
        await status_msg.delete()


# ---------------- ОЖИВЛЕНИЕ ФОТО (ВИДЕО) ----------------

@router.message(F.text == "🎬 Оживить фото")
async def start_video(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    balance = await db.get_balance(user_id)
    if balance < 5:
        return await message.answer("❌ Нужно минимум 5 ⚡.", reply_markup=main_kb())

    await message.answer("📸 **Пришлите фото для оживления:**", reply_markup=cancel_kb(), parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_video_photo)


@router.message(PhotoProcess.waiting_for_video_photo, F.photo)
async def on_video_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="5 секунд (5 ⚡)", callback_data="v_dur_5")],
        [InlineKeyboardButton(text="10 секунд (10 ⚡)", callback_data="v_dur_10")]
    ])
    await message.answer("⏳ **Выберите длительность:**", reply_markup=kb, parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_duration)


@router.callback_query(F.data.startswith("v_dur_"))
async def on_duration(callback: types.CallbackQuery, state: FSMContext):
    duration = int(callback.data.split("_")[2])
    await state.update_data(duration=duration)
    await callback.message.edit_text(f"✅ Длительность: **{duration} сек**", parse_mode="Markdown")
    await callback.message.answer("✍️ **Опишите движение:**", reply_markup=cancel_kb(), parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_video_prompt)
    await callback.answer()


@router.message(PhotoProcess.waiting_for_video_prompt)
async def on_video_prompt(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("✍️ Пожалуйста, опишите движение.")

    video_prompt = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()
    duration = data.get("duration", 5)
    model_key = f"kling_{duration}"

    if not await has_balance(user_id, model_key):
        return await message.answer("❌ Недостаточно генераций.", reply_markup=main_kb())

    status_msg = await message.answer(f"🎬 **Создаю видео...**", parse_mode="Markdown")

    try:
        photo_url = await get_telegram_photo_url(message.bot, data["photo_id"])
        video_bytes, _ = await generate_video(photo_url, video_prompt, model_key)

        if not video_bytes:
            await message.answer("⚠️ Ошибка видео.", reply_markup=main_kb())
            return

        await charge(user_id, model_key)
        video_file = BufferedInputFile(video_bytes, filename=f"video_{user_id}.mp4")
        await message.answer_video(video=video_file, caption=f"✅ **Готово!**", reply_markup=main_kb())
        await state.clear()
    except Exception as e:
        await message.answer("❌ Ошибка при создании видео.", reply_markup=main_kb())
    finally:
        await status_msg.delete()