from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# --- Выбор модели генерации изображения ---
def model_inline() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора модели ИИ для генерации фото.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🍌 NanoBanana — 1 ⚡",
                    callback_data="model_nanabanana",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 NanoBanana PRO — 5 ⚡",
                    callback_data="model_nanabanana_pro",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎨 SeeDream 4.5 — 2 ⚡",
                    callback_data="model_seedream",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_flow",  # не конфликтует с текстовой кнопкой "❌ Отменить"
                )
            ],
        ]
    )


# --- Выбор режима оживления ---
def kling_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎬 Kling 5 сек — 5 ⚡",
                    callback_data="model_kling_5",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎬 Kling 10 сек — 10 ⚡",
                    callback_data="model_kling_10",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎭 Motion Control — 5/10 ⚡",
                    callback_data="model_kling_motion",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_flow",
                )
            ],
        ]
    )


# --- Motion Control: Выбор режима качества ---
def motion_control_mode_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎬 720p (5 ⚡)", callback_data="motion_mode_720p"),
                InlineKeyboardButton(text="🎬 1080p (10 ⚡)", callback_data="motion_mode_1080p"),
            ]
        ]
    )


# --- Motion Control: Выбор ориентации персонажа ---
def motion_control_orientation_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📷 По изображению (макс 10с)",
                    callback_data="motion_orient_image",
                ),
                InlineKeyboardButton(
                    text="🎥 По видео (макс 30с)",
                    callback_data="motion_orient_video",
                ),
            ]
        ]
    )


# --- Кнопки пополнения баланса ---
def buy_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="10 ген. — 149₽", callback_data="pay_10_149")],
            [InlineKeyboardButton(text="25 ген. — 375₽", callback_data="pay_25_375")],
            [InlineKeyboardButton(text="45 ген. — 675₽", callback_data="pay_45_675")],
            [InlineKeyboardButton(text="60 ген. — 900₽", callback_data="pay_60_900")],
        ]
    )