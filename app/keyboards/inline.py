from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def model_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍌 NanoBanana (5 ген.)", callback_data="model_nanabanana")],
        [InlineKeyboardButton(text="🌊 SeaDream (10 ген.)", callback_data="model_seadream")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def buy_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 ген. — 149₽", callback_data="pay_10_149")],
        [InlineKeyboardButton(text="25 ген. — 375₽", callback_data="pay_25_375")],
        [InlineKeyboardButton(text="45 ген. — 675₽", callback_data="pay_45_675")],
        [InlineKeyboardButton(text="60 ген. — 900₽", callback_data="pay_60_900")],
    ])
