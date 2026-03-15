import logging
import traceback
import asyncio
from typing import List

from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from app.states import PhotoProcess
from app.keyboards.reply import main_kb, cancel_kb
from app.keyboards.inline import model_inline, kling_inline
from app.services.telegram_file import (
    get_telegram_photo_url,
    download_telegram_file,
    bytes_to_base64_data_uri,
)
from app.services.generation import has_balance, generate, charge, generate_video

router = Router()

MODEL_NAMES = {
    "nanabanana": "🍌 NanoBanana",
    "nanabanana_pro": "💎 NanoBanana PRO",
    "seedream": "🌊 SeeDream 4.5",
    "kling_5": "🎬 Оживить фото (5 сек)",
    "kling_10": "🎬 Оживить фото (10 сек)",
    "kling_motion": "🎭 Motion Control"
}

active_tasks = set()


async def _build_image_sources(bot: Bot, file_ids: List[str]) -> List[str]:
    """
    Для каждого file_id:
    1) пытаемся получить URL (Telegraph/TG),
    2) если не вышло — скачиваем и конвертим в data URI.
    """
    sources: List[str] = []

    for p_id in file_ids:
        src = await get_telegram_photo_url(bot, p_id)
        if src:
            sources.append(src)
            continue

        file_bytes, mime = await download_telegram_file(bot, p_id)
        if file_bytes and mime.startswith("image/"):
            sources.append(bytes_to_base64_data_uri(file_bytes, mime))

    if sources:
        first_type = "data_uri" if sources[0].startswith("data:") else "url"
    else:
        first_type = "none"

    logging.info("photo sources prepared: count=%s first_type=%s", len(sources), first_type)
    return sources


# --- ФОНОВЫЕ ЗАДАЧИ ---

async def background_photo_gen(bot: Bot, chat_id: int, photo_ids: List[str], prompt: str, model: str, user_id: int):
    """Фоновая генерация фото"""
    try:
        photo_sources = await _build_image_sources(bot, photo_ids)

        if not photo_sources:
            await bot.send_message(chat_id, "⚠️ Не удалось подготовить фото-референс.")
            return

        result = await generate(photo_sources, prompt, model)
        if not result or not result[0]:
            await bot.send_message(chat_id, "⚠️ Не удалось получить результат от нейросети.")
            return

        img_bytes, ext, _ = result
        input_file = BufferedInputFile(img_bytes, filename=f"result_{user_id}.{ext}")

        await bot.send_photo(
            chat_id=chat_id,
            photo=input_file,
            caption=f"✨ Ваше изображение готово! ({MODEL_NAMES.get(model)})",
            reply_markup=main_kb()
        )
        await charge(user_id, model)
    except Exception as e:
        logging.error(f"❌ [PHOTO ERROR]: {e}")
        await bot.send_message(chat_id, "⚠️ Ошибка при создании фото.")

    @router.message()
    async def _photo_debug_all(message: types.Message, state: FSMContext):
        current_state = await state.get_state()
        logging.info(
            "PHOTO DEBUG catch-all: text=%r, state=%r, content_type=%s",
            message.text,
            current_state,
            message.content_type,
        )