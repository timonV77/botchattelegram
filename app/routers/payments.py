from aiohttp import web
from aiogram import Router, types, F
from urllib.parse import urlencode
import os
from app.bot import bot
from app.keyboards.reply import main_kb
import database as db

router = Router()

# Берем URL из переменных или используем ваш по умолчанию
PRODAMUS_BASE_URL = os.getenv("PRODAMUS_URL", "https://ai-photo-nano.payform.ru")


# --- ВЕБХУК ДЛЯ ПРИЕМА ОПЛАТ ---
async def prodamus_webhook(request):
    """Обработчик уведомлений от Продамуса"""
    # Получаем данные POST-запроса
    data = await request.post()

    # Логируем для проверки в Railway Logs
    print(f"DEBUG: Входящий запрос от Prodamus: {dict(data)}")

    payment_status = data.get("payment_status")

    # ВАЖНО: Берем именно order_num, так как Продамус присылает наш ID туда
    order_data = data.get("order_num")

    if payment_status == "success" and order_data:
        try:
            order_str = str(order_data)

            # Проверка формата: должен быть 'user_id_amount'
            if "_" not in order_str:
                print(f"⚠️ ОШИБКА: В order_num нет разделителя '_': {order_str}")
                return web.Response(text="Wrong order format", status=200)

            # Разбиваем строку (например, "7131665196_10")
            parts = order_str.split("_")
            user_id = int(parts[0])
            amount = int(parts[1])

            # Начисляем в базу данных Supabase
            db.update_balance(user_id, amount)

            print(f"✅ УСПЕХ: Начислено {amount} генов пользователю {user_id}")

            # Уведомляем пользователя в Telegram
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

            # Отвечаем Продамусу, что всё ок
            return web.Response(text="OK", status=200)

        except Exception as e:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА В ВЕБХУКЕ: {e}")
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
        "⚡ **Выберите пакет генераций:**\n\n"
        "Оплата проходит через защищенную систему Prodamus.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("pay_"))
async def create_payment_link(callback: types.CallbackQuery):
    _, amount, price = callback.data.split("_")
    user_id = callback.from_user.id

    # Эти данные уйдут в Продамус и вернутся к нам в order_num
    params = {
        "do": "pay",
        "order_id": f"{user_id}_{amount}",
        "products[0][name]": f"Пакет {amount} генераций",
        "products[0][price]": price,
        "products[0][quantity]": 1,
        "sys": "telegram_bot"
    }

    payment_url = f"{PRODAMUS_BASE_URL}/?{urlencode(params)}"

    pay_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_tariffs")]
    ])

    await callback.message.edit_text(
        f"💎 **Вы выбрали:** {amount} генераций\n"
        f"💰 **Сумма:** {price}₽\n\n"
        "Нажмите кнопку ниже для оплаты:",
        reply_markup=pay_kb,
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(callback: types.CallbackQuery):
    await show_deposit_menu(callback.message)
    await callback.answer()