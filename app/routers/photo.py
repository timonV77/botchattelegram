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

# ВАЖНО: Используем глобальный объект бота для фоновых задач
from app.bot import bot as global_bot


active_tasks = set()
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
    # Создаем локальный экземпляр бота специально для этой задачи
    # Это гарантирует, что у него будет своя сессия, которая не закроется вебхуком
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    local_bot = Bot(
        token=global_bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    try:
        logging.info(f"🚀 [TASK START] Юзер {user_id}")

        # 1. Получаем ссылки
        photo_urls = []
        for p_id in photo_ids:
            url = await get_telegram_photo_url(global_bot, p_id)
            if url: photo_urls.append(url)

        # 2. Генерация
        img_bytes, ext = await generate(photo_urls, prompt, model)
        if not img_bytes:
            await local_bot.send_message(chat_id, "❌ Ошибка генерации.")
            return

        # 3. ОТПРАВКА
        logging.info(f"📤 [TASK] Пробую отправить через локальный коннектор...")
        file = BufferedInputFile(img_bytes, filename=f"res_{user_id}.{ext or 'jpg'}")

        # Используем local_bot вместо global_bot
        await local_bot.send_photo(
            chat_id=chat_id,
            photo=file,
            caption="✨ Ваше изображение готово!",
            reply_markup=main_kb(),
            request_timeout=300
        )

        logging.info(f"✅ [TASK SUCCESS] Фото улетело юзеру {user_id}!")
        await charge(user_id, model)

    except Exception as e:
        logging.error(f"❌ [TASK FAILED] Ошибка: {e}")
    finally:
        # Важно закрыть сессию локального бота
        await local_bot.session.close()
        logging.info(f"🧹 Сессия локального бота закрыта")

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
        "🖼 Пришлите от 1 до 4 фотографий:",
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
    await message.answer(f"{text}\n\n🤖 Выберите нейросеть:", reply_markup=model_inline())
    await state.set_state(PhotoProcess.waiting_for_model)

@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")
    await state.update_data(chosen_model=model_key)

    await callback.message.edit_text(f"🎯 Выбрана модель: {MODEL_NAMES.get(model_key, model_key)}")
    await callback.message.answer("✍️ Что изменить на фото?", reply_markup=cancel_kb())
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

    # 🔥 СОЗДАЕМ ЗАДАЧУ
    task = asyncio.create_task(
        background_photo_gen(message.chat.id, photo_ids, message.text, model, user_id)
    )

    # ❗️ ВАЖНО: Добавляем в глобальный список, чтобы Python не "забыл" про неё
    active_tasks.add(task)
    # Удаляем из списка, когда задача завершится
    task.add_done_callback(active_tasks.discard)

    await message.answer(
        "⏳ Генерация запущена! Это займет 1-3 минуты.",
        reply_markup=cancel_kb()
    )
    await state.clear()