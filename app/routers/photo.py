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

# ВАЖНО: Импортируем глобальный объект бота, чтобы сессия не умирала вместе с вебхуком
from app.bot import bot as global_bot

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
        chat_id: int,
        photo_ids: List[str],
        prompt: str,
        model: str,
        user_id: int
):
    try:
        logging.info(f"🚀 [TASK START] Запуск генерации для юзера {user_id}")

        # 1️⃣ Получаем URL фотографий
        photo_urls = []
        for p_id in photo_ids:
            try:
                url = await get_telegram_photo_url(global_bot, p_id)
                photo_urls.append(url)
            except Exception as e:
                logging.error(f"❌ Ошибка получения URL фото {p_id}: {e}")

        if not photo_urls:
            await global_bot.send_message(chat_id, "❌ Не удалось загрузить ваши фото. Попробуйте еще раз.")
            return

        logging.info(f"🔗 [TASK] Получено URL: {len(photo_urls)}")

        # 2️⃣ Генерация (процесс может идти долго)
        img_bytes, ext = await generate(photo_urls, prompt, model)

        if not img_bytes or len(img_bytes) < 1000:
            logging.error(f"❌ [TASK] Ошибка: API вернуло пустой файл или ошибку")
            await global_bot.send_message(chat_id, "❌ Нейросеть не смогла обработать запрос. Попробуйте другой промпт.")
            return

        logging.info(f"✅ [TASK] Генерация завершена. Размер: {len(img_bytes)} байт")

        # 3️⃣ Отправка в Telegram (используем глобальный бот и большой таймаут)
        file = BufferedInputFile(img_bytes, filename=f"result.{ext or 'jpg'}")

        logging.info(f"📤 [TASK] Отправка фото в чат {chat_id}...")

        await global_bot.send_photo(
            chat_id=chat_id,
            photo=file,
            caption="✨ Ваше изображение готово!",
            reply_markup=main_kb(),
            request_timeout=180  # Таймаут 3 минуты на загрузку в Telegram
        )

        logging.info(f"✅ [TASK SUCCESS] Фото успешно доставлено юзеру {user_id}")

        # 4️⃣ Списание баланса только после успеха
        await charge(user_id, model)
        logging.info(f"💰 [TASK] Баланс списан у {user_id}")

    except Exception:
        logging.error(f"❌ [TASK CRITICAL] ОШИБКА ФОНОВОЙ ГЕНЕРАЦИИ:\n{traceback.format_exc()}")
        try:
            await global_bot.send_message(chat_id, "❌ Произошла ошибка при генерации. Мы уже уведомлены и чиним её!")
        except:
            pass


# ================================
# 🔥 ФОНОВАЯ ГЕНЕРАЦИЯ ВИДЕО
# ================================
async def background_video_gen(
        chat_id: int,
        photo_ids: List[str],
        prompt: str,
        model_key: str,
        user_id: int
):
    try:
        logging.info(f"🎬 [TASK START] Запуск видео для {user_id}")

        photo_url = await get_telegram_photo_url(global_bot, photo_ids[0])

        video_bytes, ext = await generate_video(photo_url, prompt, model_key)

        if not video_bytes:
            await global_bot.send_message(chat_id, "⚠️ Не удалось создать видео. Попробуйте позже.")
            return

        video_file = BufferedInputFile(video_bytes, filename=f"video_{user_id}.mp4")

        logging.info("📤 [TASK] Отправка видео...")

        await global_bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption="✅ Ваше видео готово!",
            reply_markup=main_kb(),
            request_timeout=300  # Видео тяжелее, даем 5 минут
        )

        logging.info("✅ [TASK SUCCESS] Видео отправлено")

        await charge(user_id, model_key)
        logging.info("💰 [TASK] Баланс списан")

    except Exception:
        logging.error(f"❌ [TASK CRITICAL] ОШИБКА ФОНОВОГО ВИДЕО:\n{traceback.format_exc()}")
        try:
            await global_bot.send_message(chat_id, "❌ Ошибка при создании видео.")
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
        return await message.answer("❌ Недостаточно генераций для фотосессии.", reply_markup=main_kb())

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
        "✍️ Что изменить на фото? (Напишите промпт, например: 'сделай меня викингом' или 'добавь неоновый свет')",
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
        return await message.answer("❌ Фото потерялись. Начните заново.", reply_markup=main_kb())

    # 🔥 Запуск фоновой задачи
    asyncio.create_task(
        background_photo_gen(
            message.chat.id,
            photo_ids,
            message.text,
            model,
            user_id
        )
    )

    # Мы НЕ очищаем state сразу, чтобы юзер видел кнопку "Отмена"
    # или просто понимал, что он в режиме ожидания.
    await message.answer(
        "⏳ Магия началась! Обычно это занимает 1-3 минуты.\n\n"
        "Вы можете подождать здесь или нажать «Отменить», чтобы прервать ожидание (но генерация все равно завершится).",
        reply_markup=cancel_kb()  # Вернули кнопку Отмена
    )

    # Очищаем состояние только ПОСЛЕ того, как дали ответ,
    # либо можно оставить его до момента получения фото (по желанию).
    await state.clear()