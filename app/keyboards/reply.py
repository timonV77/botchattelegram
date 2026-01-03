from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


def main_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    # Кнопки должны в точности совпадать с текстом в роутерах!
    builder.row(KeyboardButton(text="📸 Начать фотосессию"))
    builder.row(KeyboardButton(text="🎬 Оживить фото"))
    builder.row(
        KeyboardButton(text="💰 Мой баланс"),
        KeyboardButton(text="💳 Пополнить")
    )
    builder.row(KeyboardButton(text="🆘 Помощь"))

    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="Выберите действие в меню 👇"
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="❌ Отменить"))
    return builder.as_markup(resize_keyboard=True)


def support_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="👤 Связаться с поддержкой",
        url="https://t.me/essmirraaa"
    ))
    return builder.as_markup()


def deposit_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⚡ 10 генераций — 149₽", callback_data="pay_10_149"))
    builder.row(InlineKeyboardButton(text="⚡ 25 генераций — 375₽", callback_data="pay_25_375"))
    builder.row(InlineKeyboardButton(text="⚡ 45 генераций — 675₽", callback_data="pay_45_675"))
    builder.row(InlineKeyboardButton(text="⚡ 60 генераций — 900₽", callback_data="pay_60_900"))
    return builder.as_markup()