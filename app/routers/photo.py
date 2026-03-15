import logging
import traceback
import asyncio
import aiohttp
from typing import List, Optional

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from app.states import PhotoProcess
from app.keyboards.reply import main_kb, cancel_kb
from app.keyboards.inline import (
    model_inline, kling_inline, motion_control_mode_inline,
    motion_control_orientation_inline
)
from app.services.telegram_file import get_telegram_photo_url, get_telegram_video_url
from app.services.generation import has_balance, generate, charge, generate_video

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


# --- ФОНОВЫЕ ЗАДАЧИ ---

async def background_photo_gen(chat_id: int, photo_ids: List[str], prompt: str, model: str, user_id: int):
    """Фоновая генерация фото"""
    try:
        photo_urls = []
        for p_id in photo_ids:
            url = await get_telegram_photo_url(global_bot, p_id)
            if url: photo_urls.append(url)

        # Вызываем наш новый диспетчер
        result = await generate(photo_urls, prompt, model)
        if not result or not result[0]:
            await global_bot.send_message(chat_id, "⚠️ Не удалось получить результат от нейросети.")
            return

        img_bytes, ext, _ = result
        input_file = BufferedInputFile(img_bytes, filename=f"result_{user_id}.{ext}")

        await global_bot.send_photo(
            chat_id=chat_id,
            photo=input_file,
            caption=f"✨ Ваше изображение готово! ({MODEL_NAMES.get(model)})",
            reply_markup=main_kb()
        )
        await charge(user_id, model)
    except Exception as e:
        logging.error(f"❌ [PHOTO ERROR]: {e}")
        await global_bot.send_message(chat_id, "⚠️ Ошибка при создании фото.")


async def background_video_gen_combined(chat_id: int, photo_id: str, prompt: str, model: str, user_id: int,
                                        motion_video_id: str = None):
    """Универсальная фоновая задача для видео (обычное и Motion Control)"""
    try:
        # Получаем URL фото-персонажа
        photo_url = await get_telegram_photo_url(global_bot, photo_id)

        # Получаем URL видео-движения (если это motion control)
        motion_url = None
        if motion_video_id:
            motion_url = await get_telegram_video_url(global_bot, motion_video_id)

        final_prompt = prompt if (prompt and prompt.strip() != ".") else "High quality, cinematic"

        # Вызываем наш новый диспетчер, который сам выберет нужный класс (KlingStandard или KlingMotion)
        result = await generate_video(photo_url, final_prompt, model, motion_video_url=motion_url)

        if result and result[0]:
            video_bytes, ext, _ = result
            video_file = BufferedInputFile(video_bytes, filename=f"video_{user_id}.mp4")
            await global_bot.send_video(
                chat_id=chat_id,
                video=video_file,
                caption=f"✅ Ваше видео готово! ({MODEL_NAMES.get(model)})",
                reply_markup=main_kb()
            )
            await charge(user_id, model)
        else:
            await global_bot.send_message(chat_id, "⚠️ Не удалось сгенерировать видео. Баланс сохранен.")

    except Exception as e:
        logging.error(f"❌ [VIDEO ERROR]: {e}")
        await global_bot.send_message(chat_id, "⚠️ Произошла ошибка в процессе генерации видео.")


# --- ХЕНДЛЕРЫ ---

@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    if not await has_balance(message.from_user.id, "nanabanana"):
        return await message.answer("❌ Недостаточно генераций.")
    await state.clear()
    await message.answer("🤖 Выберите нейросеть для фото:", reply_markup=model_inline())
    await state.set_state(PhotoProcess.waiting_for_model)


@router.message(F.text == "🎬 Оживить фото")
async def start_animation(message: types.Message, state: FSMContext):
    if not await has_balance(message.from_user.id, "kling_5"):
        return await message.answer("❌ Недостаточно генераций ⚡")
    await state.clear()
    await message.answer("🎬 Выберите режим оживления:", reply_markup=kling_inline())
    await state.set_state(PhotoProcess.waiting_for_model)


@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")
    await state.update_data(chosen_model=model_key)
    await callback.message.edit_text(f"🎯 Выбрана модель: {MODEL_NAMES.get(model_key, model_key)}")
    await callback.message.answer("👤 Шаг 1: Пришлите фотографию (лицо):", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_photo)


@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_ids=[message.photo[-1].file_id])
    data = await state.get_data()
    model = data.get("chosen_model")

    if model == "kling_motion":
        await message.answer("💃 Шаг 2: Пришлите видео с движением:", reply_markup=cancel_kb())
        await state.set_state(PhotoProcess.waiting_for_motion_video)
    else:
        prompt_msg = "✍️ Опишите движение (или '.')" if "kling" in str(model).lower() else "✍️ Что изменить на фото?"
        await message.answer(prompt_msg, reply_markup=cancel_kb())
        await state.set_state(PhotoProcess.waiting_for_prompt)


@router.message(PhotoProcess.waiting_for_motion_video, F.video)
async def on_motion_video(message: types.Message, state: FSMContext):
    await state.update_data(motion_video_id=message.video.file_id)
    # По умолчанию для motion control используем 720p, чтобы не усложнять хендлеры,
    # либо можно вызвать motion_control_mode_inline() как у тебя было.
    await message.answer("✍️ Опишите детали промптом (или '.'):", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_prompt)


@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    model = data.get("chosen_model", "nanabanana")
    photo_ids = data.get("photo_ids", [])
    user_id = message.from_user.id
    prompt = message.text

    if not await has_balance(user_id, model):
        await state.clear()
        return await message.answer("❌ Недостаточно средств.", reply_markup=main_kb())

    if model == "kling_motion":
        motion_id = data.get("motion_video_id")
        task = asyncio.create_task(background_video_gen_combined(
            message.chat.id, photo_ids[0], prompt, model, user_id, motion_video_id=motion_id
        ))
        time_msg = "⏳ Магия началась! Motion Control (v2.6) занимает 7-12 минут."
    elif "kling" in model.lower():
        task = asyncio.create_task(background_video_gen_combined(
            message.chat.id, photo_ids[0], prompt, model, user_id
        ))
        time_msg = "⏳ Генерация видео началась (3-5 мин)."
    else:
        task = asyncio.create_task(background_photo_gen(message.chat.id, photo_ids, prompt, model, user_id))
        time_msg = "⏳ Генерация фото началась (1-2 мин)."

    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)
    await message.answer(time_msg, reply_markup=main_kb())
    await state.clear()