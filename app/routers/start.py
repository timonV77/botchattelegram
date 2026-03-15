import os
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from app.keyboards.reply import main_kb, support_inline_kb
from app.keyboards.inline import model_inline, kling_inline
from app.states import PhotoProcess
from app.services.generation import has_balance
import database as db

router = Router()


@router.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    """Хендлер команды /start с регистрацией и проверкой баланса."""
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or "без username"

    logging.info("🚀 Обработка /start для %s (@%s)", user_id, username)

    # 1. Обработка рефералов
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id == user_id:
            referrer_id = None

    # 2. Регистрация и баланс
    try:
        await db.create_new_user(user_id, referrer_id)
        balance = await db.get_balance(user_id)
    except Exception as e:
        logging.error("❌ Ошибка БД при старте %s: %s", user_id, e)
        balance = "—"

    welcome_text = (
        "👋 <b>Привет! Я твой личный AI-фотограф.</b>\n\n"
        "Я превращаю обычные селфи в профессиональные портреты за считанные секунды.\n\n"
        f"💰 Твой баланс: <b>{balance}</b> ⚡\n\n"
        "📸 <b>Нажми «Начать фотосессию»</b>, чтобы продолжить!"
    )

    try:
        await message.answer(
            welcome_text,
            reply_markup=main_kb(),
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error("❌ Ошибка отправки сообщения пользователю %s: %s", user_id, e)
        await message.answer(welcome_text, parse_mode="HTML")

    offer_path = "assets/offer.pdf"
    if os.path.exists(offer_path):
        try:
            await message.answer_document(
                FSInputFile(offer_path),
                caption="📄 Продолжая пользоваться ботом, вы даёте согласие с условиями оферты."
            )
        except Exception as e:
            logging.error("❌ Ошибка отправки оферты: %s", e)


# --- Кнопки главного меню ---

@router.message(F.text == "📸 Начать фотосессию")
async def start_photo_from_menu(message: types.Message, state: FSMContext):
    if not await has_balance(message.from_user.id, "nanabanana"):
        return await message.answer("❌ Недостаточно генераций.", reply_markup=main_kb())

    await state.clear()
    await message.answer("🤖 Выберите нейросеть для фото:", reply_markup=model_inline())
    await state.set_state(PhotoProcess.waiting_for_model)


@router.message(F.text == "🎬 Оживить фото")
async def start_animation_from_menu(message: types.Message, state: FSMContext):
    if not await has_balance(message.from_user.id, "kling_5"):
        return await message.answer("❌ Недостаточно генераций ⚡", reply_markup=main_kb())

    await state.clear()
    await message.answer("🎬 Выберите режим оживления:", reply_markup=kling_inline())
    await state.set_state(PhotoProcess.waiting_for_model)


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
    await message.answer("❌ Действие отменено.", reply_markup=main_kb())


@router.message(F.text == "💰 Мой баланс")
async def balance_handler(message: types.Message):
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
        logging.error("❌ Ошибка при проверке баланса: %s", e)
        await message.answer("⚠️ Не удалось получить данные о балансе.")