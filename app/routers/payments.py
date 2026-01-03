import asyncio
import os
import logging
from aiohttp import web
from aiogram import Router, types, F
from urllib.parse import urlencode

from app.bot import bot
from app.keyboards.reply import main_kb
import database as db

router = Router()

# URL страницы оплаты из переменных окружения
PRODAMUS_BASE_URL = os.getenv("PRODAMUS_URL", "https://ai-photo-nano.payform.ru")


# --- ВЕБХУК ДЛЯ ПРИЕМА ОПЛАТ ---
async def prodamus_webhook(request):
    """Обработчик уведомлений от Продамуса"""
    data = await request.post()
    raw_dict = dict(data)

    logging.info(f"💳 Входящий платеж от Prodamus: {raw_dict}")

    payment_status = data.get("payment_status")
    order_data = data.get("order_num")  # Ожидаем формат "user_id_amount"

    if payment_status == "success" and order_data:
        try:
            # Разбираем данные заказа
            p = str(order_data).split("_")
            user_id = int(p[0])
            amount = int(p[1])

            # 1. Анимация в чате пользователя
            status_msg = await bot.send_message(
                chat_id=user_id,
                text="⏳ <b>Платеж получен! Начинаем зачисление...</b>\n<code>▒▒▒▒▒▒▒▒▒▒ 0%</code>",
                parse_mode="HTML"
            )

            # 2. Начисление баланса в БД
            await db.update_balance(user_id, amount)
            await db.log_payment(user_id, amount, "success", str(order_data), raw_dict)

            await status_msg.edit_text(
                "💳 <b>Проверка транзакции завершена...</b>\n<code>█████▒▒▒▒▒ 50%</code>",
                parse_mode="HTML"
            )

            # 3. Реферальный бонус (10%)
            referrer_id = await db.get_referrer(user_id)
            bonus_text = ""
            if referrer_id:
                bonus_amount = max(1, int(amount * 0.1))
                await db.update_balance(referrer_id, bonus_amount)
                bonus_text = f"\n🎁 Ваш пригласитель получил бонус <b>{bonus_amount}</b> ⚡"

                try:
                    await bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 <b>Реферальный бонус!</b>\n\nВаш друг пополнил баланс. Вам начислено <b>{bonus_amount}</b> ⚡",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            await asyncio.sleep(0.5)
            await status_msg.edit_text(
                "⚡ <b>Генерации добавлены в ваш аккаунт!</b>\n<code>██████████ 100%</code>",
                parse_mode="HTML"
            )
            await asyncio.sleep(0.5)
            await status_msg.delete()

            # 4. Итоговое сообщение
            current_bal = await db.get_balance(user_id)
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ <b>Оплата подтверждена!</b>\n\n"
                    f"Зачислено: <b>{amount}</b> ⚡\n"
                    f"Ваш баланс: <b>{current_bal}</b> ⚡"
                    f"{bonus_text}"
                ),
                reply_markup=main_kb(),
                parse_mode="HTML"
            )
            return web.Response(text="OK", status=200)

        except Exception as e:
            logging.error(f"❌ ОШИБКА Вебхука: {e}")
            return web.Response(text="Error", status=500)

    return web.Response(text="Ignored", status=200)


# --- МЕНЮ ТАРИФОВ ---
@router.message(F.text == "💳 Пополнить")
async def show_deposit_menu(message: types.Message):
    """Вывод списка тарифов"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⚡ 10 ген. — 149₽", callback_data="pay_10_149")],
        [types.InlineKeyboardButton(text="⚡ 25 ген. — 375₽", callback_data="pay_25_375")],
        [types.InlineKeyboardButton(text="⚡ 45 ген. — 675₽", callback_data="pay_45_675")],
        [types.InlineKeyboardButton(text="⚡ 60 ген. — 900₽", callback_data="pay_60_900")],
    ])

    text = "⚡ <b>Выберите пакет генераций:</b>\n\nГенерации позволяют создавать фото и оживлять их с помощью нейросетей."

    # Проверка: вызвано ли сообщение из callback (кнопка "Назад") или текстом
    if isinstance(message, types.CallbackQuery):
        await message.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("pay_"))
async def create_payment_link(callback: types.CallbackQuery):
    """Генерация ссылки на оплату"""
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
        f"💎 <b>Пакет:</b> {amount} генераций\n"
        f"💰 <b>К оплате:</b> {price}₽\n\n"
        "Нажмите кнопку ниже для перехода к безопасной оплате:",
        reply_markup=pay_kb,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(callback: types.CallbackQuery):
    """Возврат к списку тарифов"""
    await show_deposit_menu(callback)
    await callback.answer()