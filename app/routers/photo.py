import logging
import traceback
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


# --- ГЛОБАЛЬНЫЙ ХЕНДЛЕР ОТМЕНЫ ---
@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


# ---------------- СТАТИСТИКА ----------------
@router.message(Command("counters"))
async def show_counters(message: types.Message):
    try:
        count = await db.get_users_count()
        await message.answer(f"👤 Всего зарегистрировано: `{count}` пользователей.", parse_mode="Markdown")
    except:
        await message.answer("❌ Ошибка получения статистики.")


# ---------------- ФОТОСЕССИЯ ----------------
@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    if await db.get_balance(message.from_user.id) < 1:
        return await message.answer("❌ У вас недостаточно генераций.", reply_markup=main_kb())

    await message.answer("🖼 **Пришлите фотографию:**", reply_markup=cancel_kb(), parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_photo)


@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("🤖 **Выберите нейросеть:**", reply_markup=model_inline(), parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_model)


@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")
    await state.update_data(chosen_model=model_key)
    await callback.message.edit_text(f"🎯 **Выбрана модель:** {MODEL_NAMES.get(model_key, model_key)}",
                                     parse_mode="Markdown")
    await callback.message.answer("✍️ **Что изменить на фото?**", reply_markup=cancel_kb(), parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_prompt)


@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    if not message.text: return

    user_id = message.from_user.id
    data = await state.get_data()
    model = data.get("chosen_model", "nanabanana")

    if not await has_balance(user_id, model):
        await state.clear()
        return await message.answer("❌ Недостаточно средств.", reply_markup=main_kb())

    status_msg = await message.answer(f"🚀 **Генерирую изображение...**")
    try:
        photo_url = await get_telegram_photo_url(message.bot, data["photo_id"])
        img_bytes, ext = await generate(photo_url, message.text, model)

        if not img_bytes:
            raise ValueError("API вернуло пустой файл")

        await charge(user_id, model)
        file = BufferedInputFile(img_bytes, filename=f"res.{ext or 'png'}")

        # Добавлен request_timeout для защиты от ServerDisconnectedError
        await message.answer_photo(
            photo=file,
            caption="✨ **Готово!**",
            reply_markup=main_kb(),
            request_timeout=300
        )
        await state.clear()
    except Exception as e:
        logging.error(f"❌ ОШИБКА ФОТО: {traceback.format_exc()}")
        await message.answer("❌ Ошибка при генерации.", reply_markup=main_kb())
    finally:
        try:
            await status_msg.delete()
        except:
            pass


# ---------------- ОЖИВЛЕНИЕ ФОТО (ВИДЕО) ----------------
@router.message(F.text == "🎬 Оживить фото")
async def start_video(message: types.Message, state: FSMContext):
    await state.clear()
    if await db.get_balance(message.from_user.id) < 5:
        return await message.answer("❌ Минимум 5 ⚡ для видео.", reply_markup=main_kb())

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
    await callback.message.edit_text(f"✅ Выбрано: {duration} сек.")
    await callback.message.answer("✍️ **Опишите движение:**", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_video_prompt)


@router.message(PhotoProcess.waiting_for_video_prompt)
async def on_video_prompt(message: types.Message, state: FSMContext):
    if not message.text: return

    user_id = message.from_user.id
    data = await state.get_data()
    model_key = f"kling_{data.get('duration', 5)}"

    if not await has_balance(user_id, model_key):
        await state.clear()
        return await message.answer("❌ Недостаточно ⚡", reply_markup=main_kb())

    status_msg = await message.answer("🎬 **Оживляем... Это займет 1-2 минуты.**")
    try:
        photo_url = await get_telegram_photo_url(message.bot, data["photo_id"])
        video_bytes, ext = await generate_video(photo_url, message.text, model_key)

        if not video_bytes:
            await message.answer("⚠️ Нейросеть не ответила. Попробуйте позже.", reply_markup=main_kb())
            return

        await charge(user_id, model_key)
        video_file = BufferedInputFile(video_bytes, filename=f"video_{user_id}.mp4")

        # Добавлен request_timeout для защиты от ServerDisconnectedError при отправке видео
        await message.answer_video(
            video=video_file,
            caption=f"✅ **Ваше видео готово!**\n🔥 Модель: {model_key}",
            reply_markup=main_kb(),
            request_timeout=300
        )
        await state.clear()
    except Exception as e:
        logging.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ВИДЕО: {traceback.format_exc()}")
        await message.answer("❌ Ошибка на сервере при генерации видео.", reply_markup=main_kb())
    finally:
        try:
            await status_msg.delete()
        except:
            pass