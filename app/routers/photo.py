import logging
import traceback
import asyncio
from typing import List, Optional

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from app.states import PhotoProcess
from app.keyboards.reply import main_kb, cancel_kb
from app.keyboards.inline import model_inline, kling_inline
from app.services.telegram_file import get_telegram_photo_url
from app.services.generation import has_balance, generate, charge, generate_video

# Импорт логики Motion Control из нового файла
from app.services.motion import background_motion_gen

import database as db
from app.bot import bot as global_bot

router = Router()

MODEL_NAMES = {
    "nanabanana": "🍌 NanoBanana",
    "nanabanana_pro": "💎 NanoBanana PRO",
    "seedream": "🌊 SeeDream 4.5",
    "kling_5": "🎬 Оживить фото (5 сек)",
    "kling_10": "🎬 Оживить фото (10 сек)",
    "kling_motion": "🎭 Motion Control (Лицо + Видео)"
}

active_tasks = set()


# --- СТАТИСТИКА ---
@router.message(Command("users"))
async def show_users_count(message: types.Message):
    try:
        count = await db.get_users_count()
        await message.answer(f"📊 Статистика бота\n\n👥 Всего пользователей: {count}")
    except Exception as e:
        logging.error(f"❌ Ошибка статистики: {e}")
        await message.answer("⚠️ Не удалось получить статистику.")


# --- ФОНОВЫЕ ЗАДАЧИ ---
async def background_photo_gen(chat_id: int, photo_ids: List[str], prompt: str, model: str, user_id: int):
    try:
        photo_urls = []
        for p_id in photo_ids:
            url = await get_telegram_photo_url(global_bot, p_id)
            if url: photo_urls.append(url)

        _, _, result_url = await generate(photo_urls, prompt, model)
        final_url = result_url.get("url") if isinstance(result_url, dict) else result_url

        if not final_url:
            await global_bot.send_message(chat_id, "⚠️ Не удалось получить результат.")
            return

        # Если это URL — скачиваем и отправляем как файл
        if isinstance(final_url, str) and final_url.startswith("http"):
            async with aiohttp.ClientSession() as session:
                async with session.get(final_url) as resp:
                    if resp.status == 200:
                        photo_bytes = await resp.read()
                        from aiogram.types import BufferedInputFile
                        input_file = BufferedInputFile(photo_bytes, filename="result.jpg")
                        await global_bot.send_photo(
                            chat_id=chat_id,
                            photo=input_file,
                            caption="✨ Ваше изображение готово!",
                            reply_markup=main_kb()
                        )
                    else:
                        await global_bot.send_message(chat_id, "⚠️ Не удалось скачать результат.")
                        return
        else:
            await global_bot.send_photo(
                chat_id=chat_id,
                photo=str(final_url),
                caption="✨ Ваше изображение готово!",
                reply_markup=main_kb()
            )

        await charge(user_id, model)
    except Exception as e:
        logging.error(f"❌ [PHOTO ERROR]: {e}")
        logging.error(traceback.format_exc())
        await global_bot.send_message(chat_id, "⚠️ Ошибка при отправке фото.")
async def background_video_gen(chat_id: int, photo_ids: List[str], prompt: str, model: str, user_id: int):
    try:
        photo_url = await get_telegram_photo_url(global_bot, photo_ids[0])
        final_prompt = prompt if (prompt and prompt.strip() != ".") else "Cinematic movement, high quality"
        _, _, video_url = await generate_video(photo_url, final_prompt, model)
        final_v_url = video_url.get("url") if isinstance(video_url, dict) else video_url

        await global_bot.send_video(
            chat_id=chat_id,
            video=str(final_v_url),
            caption="✅ Ваше видео готово!",
            reply_markup=main_kb()
        )
        await charge(user_id, model)
    except Exception as e:
        logging.error(f"❌ [VIDEO ERROR]: {e}")
        logging.error(traceback.format_exc())
        await global_bot.send_message(chat_id, "⚠️ Ошибка при создании видео.")


# --- ХЕНДЛЕРЫ НАВИГАЦИИ ---

@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    balance = await db.get_balance(message.from_user.id)
    if balance < 1: return await message.answer("❌ Недостаточно генераций.")
    await state.clear()
    await message.answer("🤖 Выберите нейросеть для фото:", reply_markup=model_inline())
    await state.set_state(PhotoProcess.waiting_for_model)


@router.message(F.text == "🎬 Оживить фото")
async def start_animation(message: types.Message, state: FSMContext):
    balance = await db.get_balance(message.from_user.id)
    if not await has_balance(message.from_user.id, "kling_5"):
        return await message.answer("❌ Недостаточно генераций ⚡", reply_markup=main_kb())
    await state.clear()
    await state.update_data(is_video_mode=True)
    await message.answer("🎬 Выберите режим оживления:", reply_markup=kling_inline())
    await state.set_state(PhotoProcess.waiting_for_model)


# --- ХЕНДЛЕР ВЫБОРА МОДЕЛИ ---
@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")
    await state.update_data(chosen_model=model_key)
    await callback.message.edit_text(f"🎯 Выбрана модель: {MODEL_NAMES.get(model_key, model_key)}")

    await callback.message.answer(
        "👤 **Шаг 1:** Пришлите фотографию персонажа (лицо):",
        reply_markup=cancel_kb()
    )
    await state.set_state(PhotoProcess.waiting_for_photo)


# --- ХЕНДЛЕР ПРИЕМА ФОТО ---
@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext, album: Optional[List[types.Message]] = None):
    photo_ids = [msg.photo[-1].file_id for msg in album[:4]] if album else [message.photo[-1].file_id]
    await state.update_data(photo_ids=photo_ids)

    data = await state.get_data()
    model = data.get("chosen_model")

    if model == "kling_motion":
        await message.answer(
            "💃 **Шаг 2:** Теперь пришлите **видео с движением**, которое нужно повторить:",
            reply_markup=cancel_kb()
        )
        await state.set_state(PhotoProcess.waiting_for_motion_video)
    else:
        prompt_msg = "✍️ Опишите движение (или '.')" if "kling" in str(model).lower() else "✍️ Что изменить на фото?"
        await message.answer(prompt_msg, reply_markup=cancel_kb())
        await state.set_state(PhotoProcess.waiting_for_prompt)


# --- ХЕНДЛЕР ПРИЕМА ВИДЕО (только для Motion Control) ---
@router.message(PhotoProcess.waiting_for_motion_video, F.video)
async def on_motion_video(message: types.Message, state: FSMContext):
    await state.update_data(motion_video_id=message.video.file_id)
    await message.answer("✍️ Опишите детали промптом (или '.'):", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_prompt)


# ✅ FIX: обработка невалидного ввода вместо видео
@router.message(PhotoProcess.waiting_for_motion_video)
async def on_motion_video_invalid(message: types.Message, state: FSMContext):
    await message.answer("⚠️ Пожалуйста, отправьте именно **видео**, а не фото или текст.", reply_markup=cancel_kb())


# --- ФИНАЛЬНЫЙ ХЕНДЛЕР (ПРОМПТ И ЗАПУСК) ---
@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    model = data.get("chosen_model", "nanabanana")
    photo_ids = data.get("photo_ids", [])
    user_id = message.from_user.id

    if not await has_balance(user_id, model):
        await state.clear()
        return await message.answer("❌ Недостаточн�� средств.", reply_markup=main_kb())

    if model == "kling_motion":
        motion_video_id = data.get("motion_video_id")
        task = asyncio.create_task(background_motion_gen(
            global_bot, message.chat.id, photo_ids[0], motion_video_id, message.text, user_id
        ))
    else:
        func = background_video_gen if "kling" in model.lower() else background_photo_gen
        task = asyncio.create_task(func(message.chat.id, photo_ids, message.text, model, user_id))

    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)

    await message.answer("⏳ Магия началась! Подождите 1-3 минуты.", reply_markup=main_kb())
    await state.clear()