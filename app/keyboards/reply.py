from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📸 Начать фотосессию")],
            [KeyboardButton(text="🎬 Оживить фото")],
            [KeyboardButton(text="👤 Мой баланс"), KeyboardButton(text="💳 Пополнить")],
            [KeyboardButton(text="🆘 Помощь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие в меню 👇"
    )

def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отменить")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# Кнопка-ссылка для хендлера "🆘 Помощь"
def support_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Связаться с поддержкой",
                    url="https://t.me/essmirraaa"
                )
            ]
        ]
    )

# Кнопки выбора тарифов для хендлера "💳 Пополнить"
def deposit_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 10 генераций — 290₽", callback_data="buy_10")],
            [InlineKeyboardButton(text="🔥 50 генераций — 990₽", callback_data="buy_50")],
            [InlineKeyboardButton(text="💎 Безлимит на день — 1490₽", callback_data="buy_unlimited")]
        ]
    )