import logging
import traceback
import asyncio
from typing import List, Optional

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from app.states import PhotoProcess
from app.keyboards.reply import main_kb, cancel_kb
from app.keyboards.inline import model_inline
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
    "kling_5": "🎬 Оживить фото (5 сек)"
}

# Чтобы задачи не убивались сборщиком мусора
active_tasks = set()


# ================================
# 🔥 ФОНОВАЯ ГЕНЕРАЦИЯ ФОТО
# ================================
async def background_photo_gen(chat_id: int, photo_ids: List[str], prompt: str, model: str, user_id: int):
    try:
        logging.info(f"🚀 [PHOTO TASK] Старт для {user_id}")

        photo_urls = []
        for p_id in photo_ids:
            url = await get_telegram_photo_url(global_bot, p_id)
            if url: photo_urls.append(url)

        img_bytes, ext = await generate(photo_urls, prompt, model)
        if not img_bytes:
            await global_bot.send_message(chat_id, "❌ API не вернуло изображение.")
            return

        logging.info(f"✅ [PHOTO TASK] Байты получены ({len(img_bytes)}). Отправка...")

        # Отправляем именно как ФОТО
        photo_file = BufferedInputFile(img_bytes, filename=f"result_{user_id}.jpg")

        await global_bot.send_photo(
            chat_id=chat_id,
            photo=photo_file,
            caption="✨ Ваше изображение готово!",
            reply_markup=main_kb(),
            request_timeout=600
        )
        logging.info(f"✅ [PHOTO SUCCESS] Отправлено юзеру {user_id}")
        await charge(user_id, model)

    except Exception as e:
        logging.error(f"❌ [PHOTO ERROR]: {e}\n{traceback.format_exc()}")
    finally:
        logging.info(f"🧹 [PHOTO TASK END] {user_id}")


# ================================
# 🔥 ФОНОВАЯ ГЕНЕРАЦИЯ ВИДЕО (ОЖИВЛЕНИЕ)
# ================================
async def background_video_gen(chat_id: int, photo_ids: List[str], prompt: str, model: str, user_id: int):
    try:
        logging.info(f"🎬 [VIDEO TASK] Старт для {user_id}")

        # Для видео берем первое фото из списка
        photo_url = await get_telegram_photo_url(global_bot, photo_ids[0])

        # Если промпт пустой (юзер просто нажал кнопку), ставим дефолт
        final_prompt = prompt if prompt and prompt.strip() != "" else "Natural movement, high quality"

        video_bytes, ext = await generate_video(photo_url, final_prompt, model)
        if not video_bytes:
            await global_bot.send_message(chat_id, "❌ Не удалось оживить фото.")
            return

        video_file = BufferedInputFile(video_bytes, filename=f"video_{user_id}.mp4")

        await global_bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption="✅ Ваше видео готово!",
            reply_markup=main_kb(),
            request_timeout=600
        )
        logging.info(f"✅ [VIDEO SUCCESS] Отправлено юзеру {user_id}")
        await charge(user_id, model)

    except Exception as e:
        logging.error(f"❌ [VIDEO ERROR]: {e}\n{traceback.format_exc()}")
    finally:
        logging.info(f"🧹 [VIDEO TASK END] {user_id}")


# ================================
# ХЕНДЛЕРЫ
# ================================

@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


# --- 1. НАЧАЛО ФОТОСЕССИИ (Обычный режим) ---
@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    balance = await db.get_balance(message.from_user.id)
    if balance < 1:
        return await message.answer("❌ Недостаточно генераций.", reply_markup=main_kb())

    await state.clear()  # Сбрасываем старые данные на всякий случай
    await message.answer("🖼 Пришлите от 1 до 4 фотографий:", reply_markup=cancel_kb())
    await state.set_state(PhotoProcess.waiting_for_photo)


# --- 2. ОЖИВИТЬ ФОТО (Вход из главного меню) ---
@router.message(F.text == "🎬 Оживить фото")
async def start_animation(message: types.Message, state: FSMContext):
    balance = await db.get_balance(message.from_user.id)
    # Проверяем минимальный баланс для видео (5 молний)
    if balance < 5:
        return await message.answer("❌ Для оживления нужно минимум 5 ⚡", reply_markup=main_kb())

    await state.clear()
    # Помечаем, что мы зашли через режим видео, но модель пока НЕ фиксируем
    await state.update_data(is_video_mode=True)

    await message.answer(
        "🎬 Режим оживления! Пришлите **одно** фото, которое хотите превратить в видео:",
        reply_markup=cancel_kb()
    )
    await state.set_state(PhotoProcess.waiting_for_photo)


# --- 3. ПРИЕМ ФОТО ---
@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext, album: Optional[List[types.Message]] = None):
    photo_ids = [msg.photo[-1].file_id for msg in album[:4]] if album else [message.photo[-1].file_id]
    data = await state.get_data()

    await state.update_data(photo_ids=photo_ids)

    # Если мы в режиме видео, предлагаем выбор длительности (5 или 10 сек)
    if data.get("is_video_mode"):
        await message.answer(
            "⏱ Выберите длительность видео:",
            reply_markup=kling_inline() # Та самая клавиатура с выбором 5 и 10 сек
        )
        await state.set_state(PhotoProcess.waiting_for_model)
    else:
        # Если обычная фотосессия, просим выбрать обычную нейросеть
        await message.answer("🤖 Выберите нейросеть:", reply_markup=model_inline())
        await state.set_state(PhotoProcess.waiting_for_model)


# --- 4. ВЫБОР МОДЕЛИ (И для фото, и для видео) ---
@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")
    await state.update_data(chosen_model=model_key)

    await callback.message.edit_text(f"🎯 Выбрана модель: {MODEL_NAMES.get(model_key, model_key)}")

    # Оставляем клавиатуру cancel_kb(), чтобы была кнопка "Отменить"
    if "kling" in model_key.lower():
        await callback.message.answer(
            "✍️ Опишите движение на видео (или просто '.', если стандартное):",
            reply_markup=cancel_kb()
        )
    else:
        await callback.message.answer("✍️ Что изменить на фото?", reply_markup=cancel_kb())

    await state.set_state(PhotoProcess.waiting_for_prompt)


# --- 5. ПРИЕМ ПРОМПТА И ЗАПУСК ---
@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    model = data.get("chosen_model", "nanabanana")
    photo_ids = data.get("photo_ids", [])
    user_id = message.from_user.id

    # Проверка баланса непосредственно перед запуском
    if not await has_balance(user_id, model):
        await state.clear()
        return await message.answer("❌ Недостаточно средств для выбранной модели.", reply_markup=main_kb())

    # Выбор функции
    func = background_video_gen if "kling" in model.lower() else background_photo_gen

    task = asyncio.create_task(func(message.chat.id, photo_ids, message.text, model, user_id))
    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)

    # Возвращаем главное меню ТОЛЬКО здесь, когда работа ушла в фон
    await message.answer(
        "⏳ Магия началась! Видео/фото придет в этот чат через 1-3 минуты.",
        reply_markup=main_kb()
    )
    await state.clear()