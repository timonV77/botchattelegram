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

# Лимиты для стабильности
PROMPT_LIMIT = 1000
CAPTION_LIMIT = 1000  # Лимит Telegram - 1024

MODEL_NAMES = {
    "nanabanana": "🍌 Nano Banana",
    "nanabanana_pro": "💎 Nano Banana PRO",
    "seadream": "🎨 SeaDream 4.5"
}


# --- СЛУЖЕБНЫЕ КОМАНДЫ ---

@router.message(Command("counters"))
async def show_counters(message: types.Message):
    try:
        count = db.get_users_count()
        await message.answer(
            f"📊 **Статистика бота**\n\n👤 Всего зарегистрировано: `{count}` пользователей.",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ Ошибка команды counters: {e}")
        await message.answer("❌ Не удалось получить статистику.")


@router.message(F.text == "❌ Отменить")
async def cancel_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


# --- БЛОК ФОТОСЕССИИ ---

@router.message(F.text == "📸 Начать фотосессию")
async def start_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if db.get_balance(user_id) < 1:
        return await message.answer("❌ У вас недостаточно генераций.")

    await message.answer("🖼 **Пришлите фотографию**, которую хотите изменить:", reply_markup=cancel_kb(),
                         parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_photo)


@router.message(PhotoProcess.waiting_for_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("🤖 **Выберите нейросеть для обработки:**", reply_markup=model_inline(), parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_model)


@router.callback_query(F.data.startswith("model_"))
async def on_model(callback: types.CallbackQuery, state: FSMContext):
    model_key = callback.data.replace("model_", "")
    await state.update_data(chosen_model=model_key)
    nice_name = MODEL_NAMES.get(model_key, model_key.replace("_", " ").title())

    await callback.message.edit_text(f"🎯 **Выбрана модель:** {nice_name}", parse_mode="Markdown")
    await callback.message.answer(
        f"✍️ **Введите описание изменений:**\nНапишите максимально подробно, что именно изменить.",
        reply_markup=cancel_kb(),
        parse_mode="Markdown"
    )
    await state.set_state(PhotoProcess.waiting_for_prompt)
    await callback.answer()


@router.message(PhotoProcess.waiting_for_prompt)
async def on_prompt(message: types.Message, state: FSMContext):
    if message.text == "❌ Отменить": return await cancel_text(message, state)

    user_id = message.from_user.id
    data = await state.get_data()

    # Обрезаем длинный промпт для безопасности
    user_prompt = message.text[:PROMPT_LIMIT]

    if "photo_id" not in data:
        await state.clear()
        return await message.answer("⚠️ **Ошибка сессии:** фото не найдено.", reply_markup=main_kb())

    model = data.get("chosen_model", "nanabanana")
    cost = cost_for(model)

    if not has_balance(user_id, cost):
        await state.clear()
        return await message.answer(f"❌ Недостаточно средств. Нужно {cost} ген.", reply_markup=main_kb())

    nice_name = MODEL_NAMES.get(model, model)
    status_msg = await message.answer(f"🚀 **Запускаю магию {nice_name}...**", parse_mode="Markdown")

    try:
        photo_url = await get_telegram_photo_url(message.bot, data["photo_id"])
        # Отправляем обрезанный промпт в нейросеть
        img_bytes, ext = await generate(photo_url, user_prompt, model)

        if img_bytes:
            charge(user_id, cost)
            file = BufferedInputFile(img_bytes, filename=f"res.{ext or 'png'}")

            # Обрезаем промпт для подписи (Telegram limit)
            safe_caption = user_prompt[:CAPTION_LIMIT]

            await message.answer_photo(
                photo=file,
                caption=(
                    f"✨ **Готово!**\nПромпт: _{safe_caption}_\n\n"
                    f"💰 Списано: `{cost}` ⚡ | Баланс: `{db.get_balance(user_id)}` ⚡"
                ),
                reply_markup=main_kb(),
                parse_mode="Markdown"
            )
            await state.clear()
        else:
            await message.answer("❌ Ошибка нейросети. Попробуйте другой запрос.", reply_markup=main_kb())
    except Exception as e:
        print(f"❌ ОШИБКА ФОТО (User {user_id}): {type(e).__name__}: {e}")
        await message.answer("❌ Произошла ошибка системы. Попробуйте более короткий текст.")
    finally:
        try:
            await status_msg.delete()
        except:
            pass


# --- БЛОК ОЖИВЛЕНИЯ (VIDEO) ---

@router.message(F.text == "🎬 Оживить фото")
async def start_video(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if db.get_balance(user_id) < 5:
        return await message.answer("❌ Нужно минимум 5 генераций.")
    await message.answer("📸 **Пришлите фото** для оживления:", reply_markup=cancel_kb(), parse_mode="Markdown")
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
    await callback.message.edit_text(f"✅ Длительность: **{duration} сек**.", parse_mode="Markdown")
    await callback.message.answer("✍️ **Опишите движение:**", reply_markup=cancel_kb(), parse_mode="Markdown")
    await state.set_state(PhotoProcess.waiting_for_video_prompt)
    await callback.answer()


@router.message(PhotoProcess.waiting_for_video_prompt)
async def on_video_prompt(message: types.Message, state: FSMContext):
    if message.text == "❌ Отменить": return await cancel_text(message, state)

    user_id = message.from_user.id
    data = await state.get_data()
    video_prompt = message.text[:PROMPT_LIMIT]  # Обрезаем

    if "photo_id" not in data:
        await state.clear()
        return await message.answer("⚠️ Ошибка: фото не найдено.", reply_markup=main_kb())

    duration = data.get("duration", 5)
    model_key = f"kling_{duration}"
    cost = cost_for(model_key)

    if not has_balance(user_id, cost):
        return await message.answer(f"❌ Недостаточно средств.", reply_markup=main_kb())

    status_msg = await message.answer(f"🎬 **Оживляю фото ({duration}с)...**\nМожет занять до 20 минут.",
                                      parse_mode="Markdown")

    try:
        photo_url = await get_telegram_photo_url(message.bot, data["photo_id"])
        video_bytes, ext = await generate_video(photo_url, video_prompt, duration)

        if video_bytes:
            charge(user_id, cost)
            video_file = BufferedInputFile(video_bytes, filename=f"video_{user_id}.mp4")
            safe_caption = video_prompt[:CAPTION_LIMIT]

            await message.answer_video(
                video=video_file,
                caption=f"✅ **Готово!**\nПромпт: _{safe_caption}_\n💰 Списано: `{cost}` ⚡",
                reply_markup=main_kb(),
                parse_mode="Markdown"
            )
            await state.clear()
        else:
            await message.answer("⚠️ Не удалось дождаться видео. Попробуйте позже.", reply_markup=main_kb())
    except Exception as e:
        print(f"❌ ОШИБКА ВИДЕО (User {user_id}): {type(e).__name__}: {e}")
        await message.answer("❌ Ошибка при создании видео.")
    finally:
        try:
            await status_msg.delete()
        except:
            pass