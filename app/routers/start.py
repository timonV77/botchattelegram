import os
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

# Импортируем клавиатуры из твоего файла
from app.keyboards.reply import main_kb, support_inline_kb
import database as db

router = Router()


@router.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    """Хендлер команды /start: регистрация, рефералы и приветствие."""
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or "без username"

    logging.info(f"🚀 Команда /start от пользователя {user_id} (@{username})")

    # 1. ОБРАБОТКА РЕФЕРАЛЬНОЙ ССЫЛКИ
    args = message.text.split()
    if len(args) > 1:
        payload = args[1]
        if payload.isdigit():
            referrer_id = int(payload)
            if referrer_id != user_id:
                await db.set_referrer(user_id, referrer_id)
                logging.info(f"🔗 Установлен реферер {referrer_id} для {user_id}")

    # 2. РЕГИСТРАЦИЯ И ПОЛУЧЕНИЕ БАЛАНСА
    try:
        balance = await db.get_balance(user_id)
    except Exception as e:
        logging.error(f"❌ Ошибка при получении баланса {user_id}: {e}")
        balance = 0

    # 3. ОТПРАВКА ПРИВЕТСТВИЯ
    welcome_text = (
        f"👋 <b>Привет! Я твой личный AI-фотограф.</b>\n\n"
        f"Я превращаю обычные селфи в профессиональные портреты за считанные секунды.\n\n"
        f"💰 Твой баланс: <b>{balance}</b> генераций.\n\n"
        f"📸 <b>Отправь мне фото</b>, выбери стиль и начни творить!"
    )

    await message.answer(
        welcome_text,
        reply_markup=main_kb(),
        parse_mode="HTML"
    )

    # 4. ОТПРАВКА ОФЕРТЫ (если файл существует)
    offer_path = "assets/offer.pdf"
    if os.path.exists(offer_path):
        try:
            await message.answer_document(
                FSInputFile(offer_path),
                caption="📄 Продолжая пользоваться ботом, вы даёте согласие с условиями оферты."
            )
        except Exception as e:
            logging.error(f"❌ Не удалось отправить PDF: {e}")


# --- ОБРАБОТКА КНОПОК НИЖНЕГО МЕНЮ ---

@router.message(F.text == "🆘 Помощь")
async def help_handler(message: types.Message):
    """Обработка нажатия на кнопку '🆘 Помощь' в Reply-меню."""
    logging.info(f"🆘 Кнопка Помощь нажата пользователем {message.from_user.id}")
    help_text = (
        "💎 <b>Нужна помощь?</b>\n\n"
        "Если у тебя возникли вопросы по оплате, генерации или работе бота — напиши нашему менеджеру.\n\n"
        "👤 <b>Поддержка:</b> @essmirraaa"
    )

    await message.answer(
        help_text,
        reply_markup=support_inline_kb(),
        parse_mode="HTML"
    )


@router.message(F.text == "❌ Отменить")
async def cancel_handler(message: types.Message, state: FSMContext):
    """Универсальная отмена любого действия."""
    await state.clear()
    await message.answer(
        "❌ Действие отменено. Вы вернулись в главное меню.",
        reply_markup=main_kb()
    )