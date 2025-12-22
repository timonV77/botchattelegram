from aiogram import Router, types, F
from aiogram.types import LabeledPrice, PreCheckoutQuery
from app.keyboards.inline import buy_inline
from app.keyboards.reply import main_kb
from app.config import get_settings
import database as db

router = Router()
settings = get_settings()

@router.message(F.text == "💳 Пополнить")
async def buy(message: types.Message):
    await message.answer("Выберите пакет генераций:", reply_markup=buy_inline())

@router.callback_query(F.data.startswith("pay_"))
async def invoice(callback: types.CallbackQuery):
    _, count, price = callback.data.split("_")
    count, price = int(count), int(price)
    prices = [LabeledPrice(label=f"{count} генераций", amount=price * 100)]
    await callback.message.answer_invoice(
        title="Пополнение баланса",
        description=f"Пакет на {count} нейро-фотосессий",
        prices=prices,
        provider_token=settings.payment_token,
        payload=f"refill_{count}",
        currency="RUB"
    )
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(pre_checkout_q: PreCheckoutQuery):
    await pre_checkout_q.bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: types.Message):
    count = int(message.successful_payment.invoice_payload.split("_")[1])
    db.add_balance(message.from_user.id, count)
    await message.answer(f"✅ Успешно! Начислено {count} генераций.", reply_markup=main_kb())
