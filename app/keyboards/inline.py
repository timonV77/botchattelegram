from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- Выбор модели генерации изображения ---
def model_inline() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора модели ИИ для генерации фото и видео.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🍌 NanoBanana — 1 ⚡",
                callback_data="model_nanabanana"
            )
        ],
        [
            InlineKeyboardButton(
                text="💎 NanoBanana PRO — 5 ⚡",
                callback_data="model_nanabanana_pro"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎨 SeeDream 4.5 — 2 ⚡",
                callback_data="model_seedream"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="cancel"
            )
        ]
    ])

def kling_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Kling 5 сек — 5 ⚡", callback_data="model_kling_5")
        ],
        [
            InlineKeyboardButton(text="🎬 Kling 10 сек — 10 ⚡", callback_data="model_kling_10")
        ],
        [
            # Новая кнопка для Motion Control
            InlineKeyboardButton(text="🎭 Motion Control (Лицо + Видео) — 10 ⚡", callback_data="model_kling_motion")
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
        ]
    ])

# --- Кнопки пополнения баланса ---
def buy_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 ген. — 149₽", callback_data="pay_10_149")],
        [InlineKeyboardButton(text="25 ген. — 375₽", callback_data="pay_25_375")],
        [InlineKeyboardButton(text="45 ген. — 675₽", callback_data="pay_45_675")],
        [InlineKeyboardButton(text="60 ген. — 900₽", callback_data="pay_60_900")],
    ])