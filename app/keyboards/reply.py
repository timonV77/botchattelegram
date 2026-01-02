from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📸 Начать фотосессию")],
            [KeyboardButton(text="🎬 Оживить фото")],
            [KeyboardButton(text="👤 Мой баланс"), KeyboardButton(text="💳 Пополнить")],
            [KeyboardButton(text="🆘 Помощь")] # Добавили кнопку в нижнее меню
        ],
        resize_keyboard=True
    )

def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отменить")]],
        resize_keyboard=True
    )

# Новая функция для кнопки-ссылки (рекомендуется)
def support_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Написать менеджеру", url="https://t.me/essmirraaa")]
        ]
    )