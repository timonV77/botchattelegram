import os
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

# Импортируем клавиатуры
from app.keyboards.reply import main_kb, support_inline_kb
import database as db

router = Router()

@router.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    """Хендлер команды /start с регистрацией и проверкой баланса."""
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or "без username"

    logging.info(f"🚀 Обработка /start для {user_id} (@{username})")

    # 1. ОБРАБОТКА РЕФЕРАЛОВ
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id == user_id:
            referrer_id = None

    # 2. РЕГИСТРАЦИЯ (Сначала создаем, потом получаем баланс)
    try:
        await db.create_new_user(user_id, referrer_id)
        balance = await db.get_balance(user_id)
    except Exception as e:
        logging.error(f"❌ Ошибка БД при старте {user_id}: {e}")
        balance = "—"

    # 3. ФОРМИРОВАНИЕ ТЕКСТА
    welcome_text = (
        f"👋 <b>Привет! Я твой личный AI-фотограф.</b>\n\n"
        f"Я превращаю обычные селфи в профессиональные портреты за считанные секунды.\n\n"
        f"💰 Твой баланс: <b>{balance}</b> ⚡\n\n"
        f"📸 <b>Отправь мне фото</b>, чтобы начать!"
    )

    # 4. ОТПРАВКА (с обработкой ошибок клавиатуры)
    try:
        await message.answer(
            welcome_text,
            reply_markup=main_kb(),
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"❌ Ошибка отправки сообщения пользователю {user_id}: {e}")
        # Запасной вариант без клавиатуры, если она сломана
        await message.answer(welcome_text, parse_mode="HTML")

    # 5. БЕЗОПАСНАЯ ОТПРАВКА ОФЕРТЫ
    offer_path = "assets/offer.pdf"
    if os.path.exists(offer_path):
        try:
            await message.answer_document(
                FSInputFile(offer_path),
                caption="📄 Продолжая пользоваться ботом, вы даёте согласие с условиями оферты."
            )
        except Exception as e:
            logging.error(f"❌ Ошибка отправки оферты: {e}")

# --- ДОПОЛНИТЕЛЬНЫЕ КНОПКИ ---

@router.message(F.text == "🆘 Помощь")
async def help_handler(message: types.Message):
    help_text = (
        "💎 <b>Нужна помощь?</b>\n\n"
        "Если возникли вопросы по оплате или работе бота — напишите нам.\n\n"
        "👤 <b>Поддержка:</b> @essmirraaa"
    )
    await message.answer(
        help_text,
        reply_markup=support_inline_kb(),
        parse_mode="HTML"
    )

@router.message(F.text == "❌ Отменить")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=main_kb()
    )


@router.message(F.text == "💰 Мой баланс")
async def balance_handler(message: types.Message):
    """Обработка кнопки баланса из главного меню."""
    user_id = message.from_user.id
    try:
        balance = await db.get_balance(user_id)
        await message.answer(
            f"👤 <b>Ваш профиль</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"⚡ Доступно генераций: <b>{balance}</b>\n\n"
            f"🔗 Ваша реферальная ссылка:\n"
            f"<code>https://t.me/neuro_photo3_bot?start={user_id}</code>\n\n"
            f"<i>Приглашайте друзей и получайте 10% от их пополнений!</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке баланса: {e}")
        await message.answer("⚠️ Не удалось получить данные о балансе.")


@router.message()
async def _debug_any_message(message: types.Message, state: FSMContext):
    st = await state.get_state()
    logging.info(
        "DEBUG start.catch_all: text=%r content_type=%s state=%r",
        message.text,
        message.content_type,
        st
    )