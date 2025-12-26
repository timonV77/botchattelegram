from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from urllib.parse import urlencode
from app.bot import bot
import database as db

router = Router()

# ЗАМЕНИТЕ НА ВАШ РЕАЛЬНЫЙ АДРЕС ПРОДАМУСА
PRODAMUS_BASE_URL = "https://ai-photo-nano.payform.ru/"


@router.message(F.text == "💳 Пополнить")
async def show_deposit_menu(message: types.Message):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="10 ген. — 149₽", callback_data="pay_10_149")],
        [types.InlineKeyboardButton(text="25 ген. — 375₽", callback_data="pay_25_375")],
        [types.InlineKeyboardButton(text="45 ген. — 675₽", callback_data="pay_45_675")],
        [types.InlineKeyboardButton(text="60 ген. — 900₽", callback_data="pay_60_900")],
    ])

    await message.answer(
        "⚡ **Выберите пакет генераций для покупки:**\n\n"
        "После выбора тарифа вы получите ссылку на защищенную оплату.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("pay_"))
async def create_payment_link(callback: types.CallbackQuery):
    # Разбираем callback: pay_10_149 -> amount=10, price=149
    _, amount, price = callback.data.split("_")
    user_id = callback.from_user.id

    # Формируем параметры запроса по документации Продамуса
    params = {
        "do": "pay",
        "order_id": f"{user_id}_{amount}",  # Склеиваем ID юзера и кол-во генов
        "products[0][name]": f"Пополнение {amount} генераций",
        "products[0][price]": price,
        "products[0][quantity]": 1,
        "customer_extra": f"User ID: {user_id}",
        "sys": "telegram_bot"
    }

    # Собираем финальную ссылку
    payment_url = f"{PRODAMUS_BASE_URL}/?{urlencode(params)}"

    # Создаем кнопку для перехода к оплате
    pay_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💳 Оплатить заказ", url=payment_url)],
        [types.InlineKeyboardButton(text="⬅️ Назад к тарифам", callback_data="back_to_tariffs")]
    ])

    await callback.message.edit_text(
        f"💎 **Ваш заказ:** {amount} генераций\n"
        f"💰 **К оплате:** {price}₽\n\n"
        "Нажмите на кнопку ниже, чтобы перейти на страницу оплаты:",
        reply_markup=pay_kb,
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(callback: types.CallbackQuery):
    # Позволяет вернуться к выбору тарифов
    await show_deposit_menu(callback.message)
    await callback.answer()