import asyncio
import os
from aiohttp import web
from aiogram import Router, types, F
from urllib.parse import urlencode

from app.bot import bot
from app.keyboards.reply import main_kb
import database as db

router = Router()

# URL страницы оплаты из переменных Railway
PRODAMUS_BASE_URL = os.getenv("PRODAMUS_URL", "https://ai-photo-nano.payform.ru")


# --- ВЕБХУК ДЛЯ ПРИЕМА ОПЛАТ ---
async def prodamus_webhook(request):
    """Обработчик уведомлений от Продамуса с анимацией обработки"""
    data = await request.post()
    raw_dict = dict(data)

    print(f"DEBUG: Входящий запрос от Prodamus: {raw_dict}")

    payment_status = data.get("payment_status")
    order_data = data.get("order_num")

    # Предварительный парсинг для логов
    temp_user_id = None
    temp_amount = 0
    if order_data and "_" in str(order_data):
        try:
            p = str(order_data).split("_")
            temp_user_id = int(p[0])
            temp_amount = int(p[1])
        except:
            pass

    if payment_status == "success" and order_data:
        try:
            order_str = str(order_data)
            if "_" not in order_str:
                db.log_payment(temp_user_id, temp_amount, "failed_format", order_str, raw_dict)
                return web.Response(text="Wrong order format", status=200)

            user_id = temp_user_id
            amount = temp_amount

            # --- АНИМАЦИЯ ОБРАБОТКИ ---
            # 1. Начало
            status_msg = await bot.send_message(
                chat_id=user_id,
                text="⏳ **Платеж получен! Начинаем обработку...**\n`▒▒▒▒▒▒▒▒▒▒ 0%`",
                parse_mode="Markdown"
            )
            await asyncio.sleep(0.7)

            # 2. Середина (имитируем проверку транзакции)
            await status_msg.edit_text(
                "💳 **Проверка транзакции банком...**\n`█████▒▒▒▒▒ 50%`",
                parse_mode="Markdown"
            )

            # В этот момент делаем реальные действия в БД
            db.update_balance(user_id, amount)
            db.log_payment(user_id, amount, "success", order_str, raw_dict)

            await asyncio.sleep(0.7)

            # 3. Финал (зачисление)
            await status_msg.edit_text(
                "⚡ **Зачисление генераций в облако...**\n`██████████ 100%`",
                parse_mode="Markdown"
            )
            await asyncio.sleep(0.6)

            # Удаляем шкалу перед финальным анонсом
            await status_msg.delete()

            # 4. Итоговое уведомление
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ **Оплата подтверждена!**\n\n"
                    f"Вам зачислено: `{amount}` ⚡\n"
                    f"Ваш текущий баланс: `{db.get_balance(user_id)}` ⚡"
                ),
                reply_markup=main_kb(),
                parse_mode="Markdown"
            )

            print(f"✅ УСПЕХ: Начислено {amount} генов пользователю {user_id}")
            return web.Response(text="OK", status=200)

        except Exception as e:
            error_msg = f"error: {str(e)}"
            db.log_payment(temp_user_id, temp_amount, error_msg, str(order_data), raw_dict)
            print(f"❌ ОШИБКА: {error_msg}")
            return web.Response(text="Error", status=500)

    # Логируем другие статусы (отмена, ожидание)
    db.log_payment(temp_user_id, temp_amount, f"ignored_{payment_status}", str(order_data), raw_dict)
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
        "После оплаты генерации будут зачислены мгновенно.",
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
        "Нажмите кнопку ниже, чтобы открыть страницу оплаты:",
        reply_markup=pay_kb,
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(callback: types.CallbackQuery):
    await show_deposit_menu(callback.message)
    await callback.answer()