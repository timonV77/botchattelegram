import logging
import traceback
import asyncio
from typing import List, Optional

from aiogram import Router, types, F, Bot
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
    "seadream": "🌊 SeeDream 4.5"
}


# --- ФОНОВАЯ ФУНКЦИЯ ДЛЯ ФОТО ---
async def background_photo_gen(bot: Bot, message: types.Message, photo_ids: List[str], prompt: str, model: str,
                               user_id: int):
    status_msg = await message.answer(f"🚀 **Запрос принят! Обрабатываю фото ({len(photo_ids)} шт.)...**")
    try:
        # Получаем URL для всех загруженных фото
        photo_urls = []
        for p_id in photo_ids:
            url = await get_telegram_photo_url(bot, p_id)
            photo_urls.append(url)

        # Передаем список URL в генератор (важно адаптировать network.py под список)
        img_bytes, ext = await generate(photo_urls, prompt, model)

        if not img_bytes:
            await message.answer("❌ API не вернуло изображение. Попробуйте другой промт.")
            return

        await charge(user_id, model)
        file = BufferedInputFile(img_bytes, filename=f"res.{ext or 'png'}")

        await bot.send_photo(
            chat_id=message.chat.id,
            photo=file,
            caption="✨ **Готово!**",
            reply_markup=main_kb(),
            request_timeout=300
        )
    except Exception:
        logging.error(f"❌ ФОНОВАЯ ОШИБКА ФОТО: {traceback.format_exc()}")
        await message.answer("❌ Ошибка при генерации. Попробуйте позже.")
    finally:
        try:
            await status_msg.delete()
        except:
            pass


# --- ФОНОВАЯ ФУНКЦИЯ ДЛЯ ВИДЕО ---
async def background_video_gen(bot: Bot, message: types.Message, photo_ids: List[str], prompt: str, model_key: str,
                               user_id: int):
    status_msg = await message.answer("🎬 **Запрос принят! Оживляем... (1-2 мин)**")
    try:
        # Для видео обычно используется только первое фото, если модель не поддерживает multi-image
        photo_url = await get_telegram_photo_url(bot, photo_ids[0])
        video_bytes, ext = await generate_video(photo_url, prompt, model_key)

        if not video_bytes:
            await message.answer("⚠️ Нейросеть не ответила. Попробуйте позже.")
            return

        await charge(user_id, model_key)
        video_file = BufferedInputFile(video_bytes, filename=f"video_{user_id}.mp4")

        await bot.send_video(
            chat_id=message.chat.id,
            video=video_file,
            caption=f"✅ **Ваше видео готово!**",
            reply_markup=main_kb(),
            request_timeout=300
        )
    except Exception:
        logging.error(f"❌ ФОНОВАЯ ОШИБКА ВИДЕО: {traceback.format_exc()}")
        await message.answer("❌ Ошибка при создании видео.")
    finally:
        try:
            await status_msg.delete()
        except:
            pass


# --- ХЕНДЛЕРЫ ---

@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


@router.message(Command("counters"))
async def show_counters(message: types.Message):
    try:
        count = await db.get_users_count()
        await message.answer(f"👤 Всего зарегистрировано: `{count}`.", parse_mode="Markdown")
    except:
        await message.answer("❌ Ошибка статистики.")


@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    balance = await db.get_balance(message.from_user.id)
    if balance < 1:
        return await message.answer("❌ Недостаточно генераций.", reply_markup=main_kb())
    await message.answer("🖼 **Пришлите от 1 до 4 фотографий (одним альбомом или по одной):**", reply_markup=cancel_kb(),
                         parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_photo)


@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext, album: Optional[List[types.Message]] = None):
    """
    Благодаря AlbumMiddleware, если прислан альбом,
    аргумент 'album' будет содержать список всех сообщений группы.
    """
    if album:
        # Извлекаем file_id из каждого сообщения в альбоме (макс 4)
        photo_ids = [msg.photo[-1].file_id for msg in album[:4]]
        text = f"✅ Получено {len(photo_ids)} фото."
    else:
        # Одиночное фото
        photo_ids = [message.photo[-1].file_id]
        text = "✅ Фото получено."

    await state.update_data(photo_ids=photo_ids)
    await message.answer(f"{text}\n\n🤖 **Выберите нейросеть:**", reply_markup=model_inline(), parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_model)


@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")
    await state.update_data(chosen_model=model_key)
    await callback.message.edit_text(f"🎯 **Выбрана модель:** {MODEL_NAMES.get(model_key, model_key)}")
    await callback.message.answer("✍️ **Что изменить на фото?**", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_prompt)


@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    if not message.text: return
    user_id = message.from_user.id
    data = await state.get_data()
    model = data.get("chosen_model", "nanabanana")
    photo_ids = data.get("photo_ids", [])

    if not await has_balance(user_id, model):
        await state.clear()
        return await message.answer("❌ Недостаточно средств.", reply_markup=main_kb())

    if not photo_ids:
        await message.answer("❌ Фото потерялись. Попробуйте начать заново.")
        return await state.clear()

    asyncio.create_task(background_photo_gen(message.bot, message, photo_ids, message.text, model, user_id))
    await state.clear()


@router.message(F.text == "🎬 Оживить фото")
async def start_video(message: types.Message, state: FSMContext):
    await state.clear()
    if await db.get_balance(message.from_user.id) < 5:
        return await message.answer("❌ Минимум 5 ⚡ для видео.", reply_markup=main_kb())
    await message.answer("📸 **Пришлите фото:**", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_video_photo)


@router.message(PhotoProcess.waiting_for_video_photo, F.photo)
async def on_video_photo(message: types.Message, state: FSMContext, album: Optional[List[types.Message]] = None):
    # Для видео берем только первое фото из альбома или одиночное фото
    if album:
        p_id = album[0].photo[-1].file_id
    else:
        p_id = message.photo[-1].file_id

    await state.update_data(photo_ids=[p_id])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="5 секунд (5 ⚡)", callback_data="v_dur_5")],
        [InlineKeyboardButton(text="10 секунд (10 ⚡)", callback_data="v_dur_10")]
    ])
    await message.answer("⏳ **Выберите длительность:**", reply_markup=kb)
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
    photo_ids = data.get("photo_ids", [])

    if not await has_balance(user_id, model_key):
        await state.clear()
        return await message.answer("❌ Недостаточно ⚡", reply_markup=main_kb())

    asyncio.create_task(background_video_gen(message.bot, message, photo_ids, message.text, model_key, user_id))
    await state.clear()