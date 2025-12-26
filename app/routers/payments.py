from aiohttp import web
from aiogram import Router, types, F
from urllib.parse import urlencode
from app.bot import bot
from app.keyboards.reply import main_kb  # Убедитесь, что этот импорт верный для вашей структуры
import database as db

router = Router()

# Ваш реальный адрес Продамуса
PRODAMUS_BASE_URL = "https://ai-photo-nano.payform.ru"


# --- ЭТА ФУНКЦИЯ ДОЛЖНА БЫТЬ ЗДЕСЬ ДЛЯ main.py ---
async def prodamus_webhook(request):
    """Обработчик уведомлений от Продамуса"""
    data = await request.post()
    payment_status = data.get("payment_status")
    order_id = data.get("order_id")  # Получаем нашу строку "user_id_amount"

    if payment_status == "success" and order_id:
        try:
            # Разделяем ID пользователя и количество генераций
            user_id, amount = map(int, order_id.split("_"))

            # Начисляем баланс в БД
            db.update_balance(user_id, amount)

            # Отправляем уведомление пользователю
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ **Оплата прошла успешно!**\n\n"
                    f"Вам зачислено: `{amount}` ⚡\n"
                    f"Ваш текущий баланс: `{db.get_balance(user_id)}` ⚡"
                ),
                reply_markup=main_kb(),
                parse_mode="Markdown"
            )
            return web.Response(text="OK", status=200)
        except Exception as e:
            print(f"❌ Ошибка при обработке платежа: {e}")
            return web.Response(text="Error", status=500)

    return web.Response(text="Ignored", status=200)


# --- ЛОГИКА КНОПОК ТАРИФОВ ---

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
    _, amount, price = callback.data.split("_")
    user_id = callback.from_user.id

    params = {
        "do": "pay",
        "order_id": f"{user_id}_{amount}",
        "products[0][name]": f"Пополнение {amount} генераций",
        "products[0][price]": price,
        "products[0][quantity]": 1,
        "sys": "telegram_bot"
    }

    payment_url = f"{PRODAMUS_BASE_URL}/?{urlencode(params)}"

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
    await show_deposit_menu(callback.message)
    await callback.answer()