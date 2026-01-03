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
def deposit_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # Формат: pay_КоличествоГенераций_ЦенаВРублях
    builder.row(InlineKeyboardButton(text="⚡ 10 генераций — 149₽", callback_data="pay_10_149"))
    builder.row(InlineKeyboardButton(text="⚡ 25 генераций — 375₽", callback_data="pay_25_375"))
    builder.row(InlineKeyboardButton(text="⚡ 45 генераций — 675₽", callback_data="pay_45_675"))
    builder.row(InlineKeyboardButton(text="⚡ 60 генераций — 900₽", callback_data="pay_60_900"))
    return builder.as_markup()