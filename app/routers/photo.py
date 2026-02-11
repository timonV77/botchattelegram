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
from app.services.generation import has_balance, generate, charge, generate_video
import database as db

router = Router()

MODEL_NAMES = {
    "nanabanana": "🍌 NanoBanana",
    "nanabanana_pro": "💎 NanoBanana PRO",
    "seedream": "🌊 SeeDream 4.5"
}


# ================================
# 🔥 ФОНОВАЯ ГЕНЕРАЦИЯ ФОТО
# ================================
async def background_photo_gen(
        bot: Bot,
        chat_id: int,
        photo_ids: List[str],
        prompt: str,
        model: str,
        user_id: int
):
    try:
        logging.info("🚀 Запуск фоновой генерации фото")

        # 1️⃣ Получаем URL фотографий
        photo_urls = []
        for p_id in photo_ids:
            url = await get_telegram_photo_url(bot, p_id)
            photo_urls.append(url)

        logging.info(f"🔗 Получены URL фото: {len(photo_urls)}")

        # 2️⃣ Генерация
        img_bytes, ext = await generate(photo_urls, prompt, model)

        if not img_bytes:
            await bot.send_message(chat_id, "❌ API не вернуло изображение.")
            return

        logging.info(f"✅ Генерация завершена. Размер: {len(img_bytes)} байт")

        # 3️⃣ Отправка в Telegram
        file = BufferedInputFile(img_bytes, filename=f"result.{ext or 'png'}")

        logging.info("📤 Отправляю фото в Telegram...")

        await bot.send_photo(
            chat_id=chat_id,
            photo=file,
            caption="✨ Готово!",
            reply_markup=main_kb()
        )

        logging.info("✅ Фото успешно отправлено")

        # 4️⃣ Списание ТОЛЬКО после успешной отправки
        await charge(user_id, model)
        logging.info("💰 Баланс успешно списан")

    except Exception:
        logging.error(f"❌ ОШИБКА ФОНОВОЙ ГЕНЕРАЦИИ:\n{traceback.format_exc()}")
        try:
            await bot.send_message(chat_id, "❌ Ошибка при генерации. Попробуйте позже.")
        except:
            pass


# ================================
# 🔥 ФОНОВАЯ ГЕНЕРАЦИЯ ВИДЕО
# ================================
async def background_video_gen(
        bot: Bot,
        chat_id: int,
        photo_ids: List[str],
        prompt: str,
        model_key: str,
        user_id: int
):
    try:
        logging.info("🎬 Запуск фоновой генерации видео")

        photo_url = await get_telegram_photo_url(bot, photo_ids[0])

        video_bytes, ext = await generate_video(photo_url, prompt, model_key)

        if not video_bytes:
            await bot.send_message(chat_id, "⚠️ Нейросеть не ответила.")
            return

        video_file = BufferedInputFile(video_bytes, filename=f"video_{user_id}.mp4")

        logging.info("📤 Отправляю видео в Telegram...")

        await bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption="✅ Ваше видео готово!",
            reply_markup=main_kb()
        )

        logging.info("✅ Видео отправлено")

        await charge(user_id, model_key)
        logging.info("💰 Баланс списан")

    except Exception:
        logging.error(f"❌ ОШИБКА ФОНОВОГО ВИДЕО:\n{traceback.format_exc()}")
        try:
            await bot.send_message(chat_id, "❌ Ошибка при создании видео.")
        except:
            pass


# ================================
# ХЕНДЛЕРЫ
# ================================

@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


@router.message(Command("counters"))
async def show_counters(message: types.Message):
    try:
        count = await db.get_users_count()
        await message.answer(f"👤 Всего зарегистрировано: {count}.")
    except:
        await message.answer("❌ Ошибка статистики.")


@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    balance = await db.get_balance(message.from_user.id)
    if balance < 1:
        return await message.answer("❌ Недостаточно генераций.", reply_markup=main_kb())

    await message.answer(
        "🖼 Пришлите от 1 до 4 фотографий (альбомом или по одной):",
        reply_markup=cancel_kb()
    )

    await state.set_state(PhotoProcess.waiting_for_photo)


@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext, album: Optional[List[types.Message]] = None):

    if album:
        photo_ids = [msg.photo[-1].file_id for msg in album[:4]]
        text = f"✅ Получено {len(photo_ids)} фото."
    else:
        photo_ids = [message.photo[-1].file_id]
        text = "✅ Фото получено."

    await state.update_data(photo_ids=photo_ids)

    await message.answer(
        f"{text}\n\n🤖 Выберите нейросеть:",
        reply_markup=model_inline()
    )

    await state.set_state(PhotoProcess.waiting_for_model)


@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")

    await state.update_data(chosen_model=model_key)

    await callback.message.edit_text(
        f"🎯 Выбрана модель: {MODEL_NAMES.get(model_key, model_key)}"
    )

    await callback.message.answer(
        "✍️ Что изменить на фото?",
        reply_markup=cancel_kb()
    )

    await state.set_state(PhotoProcess.waiting_for_prompt)


@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    if not message.text:
        return

    user_id = message.from_user.id
    data = await state.get_data()
    model = data.get("chosen_model", "nanabanana")
    photo_ids = data.get("photo_ids", [])

    if not await has_balance(user_id, model):
        await state.clear()
        return await message.answer("❌ Недостаточно средств.", reply_markup=main_kb())

    if not photo_ids:
        await state.clear()
        return await message.answer("❌ Фото потерялись. Начните заново.")

    # 🔥 Запуск фоновой задачи
    asyncio.create_task(
        background_photo_gen(
            message.bot,
            message.chat.id,
            photo_ids,
            message.text,
            model,
            user_id
        )
    )

    await message.answer("⏳ Генерирую...")
    await state.clear()
