import logging
import traceback
import asyncio
from typing import List, Optional
from app.network import process_motion_control
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from app.states import PhotoProcess
from app.keyboards.reply import main_kb, cancel_kb
from app.keyboards.inline import model_inline, kling_inline  # Добавил импорт kling_inline
from app.services.telegram_file import get_telegram_photo_url
from app.services.generation import has_balance, generate, charge, generate_video
import database as db

# Глобальный объект бота
from app.bot import bot as global_bot

router = Router()

MODEL_NAMES = {
    "nanabanana": "🍌 NanoBanana",
    "nanabanana_pro": "💎 NanoBanana PRO",
    "seedream": "🌊 SeeDream 4.5",
    "kling_5": "🎬 Оживить фото (5 сек)",
    "kling_10": "🎬 Оживить фото (10 сек)"
}

active_tasks = set()


@router.message(Command("users"))
async def show_users_count(message: types.Message):
    try:
        # Вызываем твою функцию из database.py
        count = await db.get_users_count()

        await message.answer(
            f"📊 Статистика бота\n\n"
            f"👥 Всего пользователей: {count}"
        )
        logging.info(f"📊 Юзер {message.from_user.id} запросил статистику: {count} чел.")
    except Exception as e:
        logging.error(f"❌ Ошибка при выполнении команды /users: {e}")
        await message.answer("⚠️ Не удалось получить статистику.")


async def background_photo_gen(chat_id: int, photo_ids: List[str], prompt: str, model: str, user_id: int):
    try:
        logging.info(f"--- 🛠 Запуск генерации фото: {model} ---")

        photo_urls = []
        for p_id in photo_ids:
            url = await get_telegram_photo_url(global_bot, p_id)
            if url:
                photo_urls.append(url)

        # Вызываем генерацию (принимает список URL, промпт и модель)
        # На выходе: (бинарные_данные, расширение, ссылка_строка)
        _, _, result_url = await generate(photo_urls, prompt, model)

        if not result_url:
            logging.error("❌ Не удалось вытащить URL фото из API (вернулся None)")
            await global_bot.send_message(chat_id, "❌ Ошибка: нейросеть не смогла сгенерировать изображение.")
            return

        # ИСПРАВЛЕНИЕ: Если вдруг пришел словарь {'url': '...'}, вынимаем строку
        final_url = result_url.get("url") if isinstance(result_url, dict) else result_url

        logging.info(f"📤 [SENDING PHOTO] Пытаюсь отправить URL: {final_url}")

        await global_bot.send_photo(
            chat_id=chat_id,
            photo=str(final_url),  # Гарантируем, что это строка
            caption="✨ Ваше изображение готово!",
            reply_markup=main_kb()
        )

        await charge(user_id, model)
        logging.info(f"✅ [SUCCESS] Фото улетело юзеру {user_id}")

    except Exception as e:
        logging.error(f"❌ [PHOTO CRITICAL ERROR]: {e}")
        logging.error(traceback.format_exc())
        await global_bot.send_message(chat_id, "⚠️ Ошибка при отправке результата. Попробуйте другой промпт.")


# ================================
# 🔥 ФОНОВАЯ ГЕНЕРАЦИЯ ВИДЕО (ЧЕРЕЗ URL)
# ================================
async def background_video_gen(chat_id: int, photo_ids: List[str], prompt: str, model: str, user_id: int):
    try:
        logging.info(f"🎬 [VIDEO TASK] Старт для {user_id}")

        photo_url = await get_telegram_photo_url(global_bot, photo_ids[0])
        # Для видео часто промпт не должен быть пустым
        final_prompt = prompt if (prompt and prompt.strip() != ".") else "Cinematic movement, high quality"

        # На выходе: (бинарные_данные, расширение, ссылка_строка)
        _, _, video_url = await generate_video(photo_url, final_prompt, model)

        if not video_url:
            logging.error("❌ Не удалось получить ссылку на видео")
            await global_bot.send_message(chat_id, "❌ Ошибка генерации видео.")
            return

        # ИСПРАВЛЕНИЕ: Извлечение строки из словаря
        final_v_url = video_url.get("url") if isinstance(video_url, dict) else video_url

        logging.info(f"📤 [SENDING VIDEO] URL: {final_v_url}")

        await global_bot.send_video(
            chat_id=chat_id,
            video=str(final_v_url),
            caption="✅ Ваше видео готово!",
            reply_markup=main_kb()
        )

        await charge(user_id, model)
        logging.info(f"✅ [VIDEO SUCCESS] Видео отправлено {user_id}")

    except Exception as e:
        logging.error(f"❌ [VIDEO ERROR]: {e}")
        logging.error(traceback.format_exc())
        await global_bot.send_message(chat_id, "⚠️ Ошибка при создании видео.")
# ================================
# ХЕНДЛЕРЫ
# ================================

# --- НОВАЯ ФОНОВАЯ ФУНКЦИЯ ДЛЯ MOTION CONTROL ---
async def background_motion_gen(chat_id: int, char_photo_id: str, motion_video_id: str, prompt: str, user_id: int):
    try:
        logging.info(f"🎭 [MOTION TASK] Старт для {user_id}")

        # Ссылки на фото персонажа и видео движения
        char_url = await get_telegram_photo_url(global_bot, char_photo_id)
        motion_url = await get_telegram_photo_url(global_bot, motion_video_id)

        # Вызов функции из network.py (теперь импорт станет активным)
        _, _, result_url = await process_motion_control(prompt, char_url, motion_url)

        if not result_url:
            await global_bot.send_message(chat_id, "❌ Ошибка API: не удалось создать видео.")
            return

        final_v_url = result_url.get("url") if isinstance(result_url, dict) else result_url

        await global_bot.send_video(
            chat_id=chat_id,
            video=str(final_v_url),
            caption="🎭 Ваше Motion Control видео готово!",
            reply_markup=main_kb()
        )

        await charge(user_id, "kling_motion")

    except Exception as e:
        logging.error(f"❌ [MOTION ERROR]: {e}")
        await global_bot.send_message(chat_id, "⚠️ Ошибка при генерации видео.")


@router.message(PhotoProcess.waiting_for_motion_video, F.video)
async def on_motion_video(message: types.Message, state: FSMContext):
    await state.update_data(motion_video_id=message.video.file_id)
    await message.answer(
        "✍️ Опишите детали движения промптом (или просто '.', если нечего добавить):",
        reply_markup=cancel_kb()
    )
    await state.set_state(PhotoProcess.waiting_for_prompt)



@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    balance = await db.get_balance(message.from_user.id)
    if balance < 1:
        return await message.answer("❌ Недостаточно генераций.", reply_markup=main_kb())
    await state.clear()
    await message.answer("🖼 Пришлите от 1 до 4 фотографий:", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_photo)


@router.message(F.text == "🎬 Оживить фото")
async def start_animation(message: types.Message, state: FSMContext):
    balance = await db.get_balance(message.from_user.id)
    if balance < 5:
        return await message.answer("❌ Для оживления нужно минимум 5 ⚡", reply_markup=main_kb())
    await state.clear()
    await state.update_data(is_video_mode=True)
    await message.answer("🎬 Режим оживления! Пришлите одно фото:", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_photo)


@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext, album: Optional[List[types.Message]] = None):
    photo_ids = [msg.photo[-1].file_id for msg in album[:4]] if album else [message.photo[-1].file_id]
    data = await state.get_data()
    await state.update_data(photo_ids=photo_ids)

    if data.get("is_video_mode"):
        await message.answer("⏱ Выберите длительность видео:", reply_markup=kling_inline())
    else:
        await message.answer("🤖 Выберите нейросеть:", reply_markup=model_inline())
    await state.set_state(PhotoProcess.waiting_for_model)


@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")
    await state.update_data(chosen_model=model_key)
    await callback.message.edit_text(f"🎯 Выбрана модель: {MODEL_NAMES.get(model_key, model_key)}")

    prompt_msg = "✍️ Опишите движение (или просто '.', если стандартное):" if "kling" in model_key.lower() else "✍️ Что изменить на фото?"
    await callback.message.answer(prompt_msg, reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_prompt)


@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    model = data.get("chosen_model", "nanabanana")
    photo_ids = data.get("photo_ids", [])
    user_id = message.from_user.id

    if not await has_balance(user_id, model):
        await state.clear()
        return await message.answer("❌ Недостаточно средств.", reply_markup=main_kb())

    # --- НОВАЯ ЛОГИКА ВЫБОРА ЗАДАЧИ ---
    if model == "kling_motion":
        # Достаем ID видео-референса, который сохранили на предыдущем шаге
        motion_video_id = data.get("motion_video_id")

        # Создаем задачу именно для Motion Control
        # Здесь мы вызываем функцию, которая внутри себя использует process_motion_control
        task = asyncio.create_task(background_motion_gen(
            message.chat.id,
            photo_ids[0],
            motion_video_id,
            message.text,
            user_id
        ))
    else:
        # Старая логика для остальных моделей (Kling 5/10 и фото)
        func = background_video_gen if "kling" in model.lower() else background_photo_gen
        task = asyncio.create_task(func(message.chat.id, photo_ids, message.text, model, user_id))
    # ---------------------------------

    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)

    await message.answer("⏳ Магия началась! Видео/фото придет в этот чат через 1-3 минуты.", reply_markup=main_kb())
    await state.clear()

