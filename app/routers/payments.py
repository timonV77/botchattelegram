import asyncio
import os
import logging
from aiohttp import web
from aiogram import Router, types, F, Bot
from urllib.parse import urlencode

from app.keyboards.reply import main_kb
import database as db

router = Router()
PRODAMUS_BASE_URL = os.getenv("PRODAMUS_URL", "https://ai-photo-nano.payform.ru")


# --- ФОНОВЫЕ ЗАДАЧИ ---

async def process_delivery_animation(bot: Bot, user_id: int, amount: int, bonus_text: str):
    """Анимация зачисления, запущенная в фоне"""
    try:
        # Используем переданный объект bot вместо глобального
        status_msg = await bot.send_message(
            chat_id=user_id,
            text="⏳ <b>Платеж получен! Начинаем зачисление...</b>\n<code>▒▒▒▒▒▒▒▒▒▒ 0%</code>",
            parse_mode="HTML"
        )
        await asyncio.sleep(0.5)
        await status_msg.edit_text(
            "💳 <b>Проверка транзакции завершена...</b>\n<code>█████▒▒▒▒▒ 50%</code>",
            parse_mode="HTML"
        )
        await asyncio.sleep(0.5)

        current_bal = await db.get_balance(user_id)
        await status_msg.delete()

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
    except Exception as e:
        logging.error(f"❌ Ошибка анимации для {user_id}: {e}")


# --- ВЕБХУК (ДЛЯ PRODAMUS) ---

async def prodamus_webhook(request: web.Request):
    """Обработчик уведомлений от платежной системы"""
    # Извлекаем бота из приложения (мы положили его туда в main.py через app['bot'] = bot)
    bot: Bot = request.app.get('bot')
    if not bot:
        logging.error("❌ Объект Bot не найден в request.app!")
        return web.Response(text="Internal Error", status=500)

    data = await request.post()
    raw_dict = dict(data)

    payment_status = data.get("payment_status")
    order_data = data.get("order_num")

    if payment_status == "success" and order_data:
        try:
            p = str(order_data).split("_")
            user_id = int(p[0])
            amount = int(p[1])

            # 1. МГНОВЕННОЕ зачисление в базу
            await db.update_balance(user_id, amount)
            await db.log_payment(user_id, amount, "success", str(order_data), raw_dict)

            # 2. Логика реферальной системы
            referrer_id = await db.get_referrer(user_id)
            bonus_text = ""
            if referrer_id:
                bonus_amount = max(1, int(amount * 0.1))
                await db.update_balance(referrer_id, bonus_amount)
                bonus_text = f"\n🎁 Ваш пригласитель получил бонус <b>{bonus_amount}</b> ⚡"

                # Уведомление рефереру (в фоне)
                asyncio.create_task(bot.send_message(chat_id=referrer_id, text="🎉 Бонус за друга!"))

            # 3. Запускаем анимацию "в фоне" и СРАЗУ отвечаем серверу платежей (200 OK)
            asyncio.create_task(process_delivery_animation(bot, user_id, amount, bonus_text))

            return web.Response(text="OK", status=200)
        except Exception as e:
            logging.error(f"❌ Ошибка обработки платежа: {e}")
            return web.Response(text="Error", status=500)

    return web.Response(text="Ignored", status=200)


# --- ХЕНДЛЕРЫ МЕНЮ ---

@router.message(F.text == "💳 Пополнить")
async def show_deposit_menu(message: types.Message):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⚡ 10 ген. — 149₽", callback_data="pay_10_149")],
        [types.InlineKeyboardButton(text="⚡ 25 ген. — 375₽", callback_data="pay_25_375")],
        [types.InlineKeyboardButton(text="⚡ 45 ген. — 675₽", callback_data="pay_45_675")],
        [types.InlineKeyboardButton(text="⚡ 60 ген. — 900₽", callback_data="pay_60_900")],
    ])
    text = "⚡ <b>Выберите пакет генераций:</b>"

    if isinstance(message, types.CallbackQuery):
        await message.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("pay_"))
async def create_payment_link(callback: types.CallbackQuery):
    _, amount, price = callback.data.split("_")
    user_id = callback.from_user.id

    # Формируем ссылку для Продамуса
    params = {
        "do": "pay",
        "order_id": f"{user_id}_{amount}",
        "products[0][name]": f"Пакет {amount} молний",
        "products[0][price]": price,
        "products[0][quantity]": 1
    }
    payment_url = f"{PRODAMUS_BASE_URL}/?{urlencode(params)}"

    pay_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_tariffs")]
    ])

    await callback.message.edit_text(f"💰 К оплате: <b>{price}₽</b>", reply_markup=pay_kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(callback: types.CallbackQuery):
    await show_deposit_menu(callback)
    await callback.answer()