import logging
import traceback
from aiohttp import web
from vkbottle.bot import Bot
import vk_database as db
from app.vk.keyboards import get_main_keyboard

import asyncio
import hmac
import hashlib
import urllib.parse
from app.config import settings

logger = logging.getLogger(__name__)

def verify_vk_signature(data: dict, received_signature: str, secret_key: str) -> bool:
    """Проверка подписи Продамуса для VK-магазина"""
    if not secret_key:
        logging.warning("⚠️ VK_PRODAMUS_KEY не задан. Проверка подписи пропущена.")
        return True
    
    if not received_signature:
        return False

    # Сортируем ключи и формируем строку данных (аналогично PHP http_build_query)
    # Prodamus ожидает сортировку ключей и формат: k1=v1&k2=v2...
    sorted_keys = sorted(data.keys())
    
    # Важно: В данных могут быть вложенные массивы (products), но обычно Продамус
    # присылает их уже "плоскими" ключами при POST-форме или мы работаем с ключами верхнего уровня.
    # Для простоты и соответствия большинству примеров Продамуса:
    filtered_data = {k: data[k] for k in sorted_keys if k != 'Sign'}
    data_string = urllib.parse.urlencode(filtered_data)
    
    computed_signature = hmac.new(
        secret_key.encode('utf-8'),
        data_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(computed_signature.lower(), received_signature.lower())


async def process_delivery_animation(bot: Bot, user_id: int, amount: int, bonus_text: str):
    """Анимация зачисления, запущенная в фоне (аналог ТГ)"""
    logger.info(f"[ANIM] Запуск анимации для user={user_id}, amount={amount}")
    try:
        # 1. Начало
        await bot.api.messages.send(
            user_id=user_id,
            message="⏳ Платеж получен! Начинаем зачисление...\n▒▒▒▒▒▒▒▒▒▒ 0%",
            random_id=0
        )
        await asyncio.sleep(1.5)

        # 2. Прогресс
        await bot.api.messages.send(
            user_id=user_id,
            message="💳 Проверка транзакции завершена...\n█████▒▒▒▒▒ 50%",
            random_id=0
        )
        # ВАЖНО: читаем баланс ПОСЛЕ того как update_balance уже выполнился в webhook.
        # Даём небольшую паузу чтобы гарантированно увидеть новые данные из БД.
        await asyncio.sleep(2.0)

        current_bal = await db.get_balance(user_id)
        logger.info(f"[ANIM] Баланс после зачисления для user={user_id}: {current_bal} руб.")

        await bot.api.messages.send(
            user_id=user_id,
            message=(
                f"✅ Оплата подтверждена!\n\n"
                f"Зачислено: {amount} руб.\n"
                f"Ваш баланс: {current_bal} руб."
                f"{bonus_text}"
            ),
            keyboard=get_main_keyboard(user_id),
            random_id=0
        )
        logger.info(f"[ANIM] Анимация завершена для user={user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка анимации VK для user={user_id}: {e}\n{traceback.format_exc()}")


async def prodamus_vk_webhook(request: web.Request):
    """Обработчик уведомлений от Продамуса для VK бота"""
    logger.info("="*60)
    logger.info(f"[WEBHOOK] Входящий запрос: {request.method} {request.path}")
    logger.info(f"[WEBHOOK] Заголовки: {dict(request.headers)}")

    bot: Bot = request.app.get('bot')
    if not bot:
        logger.error("❌ Объект Bot не найден в request.app для VK!")
        return web.Response(text="Internal Error", status=500)

    # 1. Получаем данные
    data = {}
    raw_body = b""
    try:
        raw_body = await request.read()
        logger.info(f"[WEBHOOK] Raw body ({len(raw_body)} bytes): {raw_body[:2000]}")

        post_data = await request.post()
        if post_data:
            data.update(post_data)
            logger.info(f"[WEBHOOK] Распарсено как form-data: {dict(data)}")

        if not data:
            try:
                json_data = await request.json()
                if json_data:
                    data.update(json_data)
                    logger.info(f"[WEBHOOK] Распарсено как JSON: {dict(data)}")
            except Exception as je:
                logger.warning(f"[WEBHOOK] JSON parse failed: {je}")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось распарсить тело VK платежа: {e}\n{traceback.format_exc()}")

    if not data:
        logger.error("[WEBHOOK] ❌ data пустой — тело запроса не распознано!")
        return web.Response(text="Bad Request", status=400)

    # 2. Проверка подписи
    received_sign = request.headers.get("Sign") or data.get("Sign")
    logger.info(f"[WEBHOOK] Подпись из запроса: {received_sign!r}")
    logger.info(f"[WEBHOOK] VK_PRODAMUS_KEY задан: {bool(settings.vk_prodamus_key)}")

    sig_ok = verify_vk_signature(data, received_sign, settings.vk_prodamus_key)
    logger.info(f"[WEBHOOK] Результат проверки подписи: {sig_ok}")

    if not sig_ok:
        logger.error(f"⛔️ Ошибка подписи VK платежа! Получено: {received_sign!r} (ВРЕМЕННО РАЗРЕШЕНО ДЛЯ ДЕБАГА)")

    # 3. Разбираем поля платежа
    payment_status = data.get("payment_status")
    order_data = data.get("order_num") or data.get("order_id")
    reported_sum = data.get("sum") or data.get("amount") or 0

    logger.info(
        f"[WEBHOOK] Разобранные поля: payment_status={payment_status!r}, "
        f"order_data={order_data!r}, reported_sum={reported_sum!r}"
    )

    if payment_status != "success":
        logger.warning(f"[WEBHOOK] payment_status={payment_status!r} — не success, игнорируем")
        return web.Response(text="Ignored", status=200)

    if not order_data:
        logger.error("[WEBHOOK] ❌ order_num/order_id отсутствует в данных!")
        return web.Response(text="Ignored", status=200)

    try:
        # Ожидаем формат: {user_id}_{amount}
        p = str(order_data).split("_")
        if len(p) >= 2:
            user_id = int(p[0])
            amount = int(p[1])
            logger.info(f"[WEBHOOK] Разобран order_data: user_id={user_id}, amount={amount}")
        else:
            vk_user_id = data.get("vk_user_id")
            logger.warning(f"[WEBHOOK] order_data нестандартный ({order_data!r}), пробуем vk_user_id={vk_user_id!r}")
            if vk_user_id and str(vk_user_id).isdigit():
                user_id = int(vk_user_id)
                amount = int(float(reported_sum))
            else:
                logger.error(f"❌ Не удалось определить пользователя VK из: order_data={order_data!r}, vk_user_id={vk_user_id!r}")
                return web.Response(text="Invalid data", status=400)

        # 4. МГНОВЕННОЕ зачисление в базу
        logger.info(f"[WEBHOOK] Вызываем db.update_balance(user_id={user_id}, amount={amount})")
        update_ok = await db.update_balance(user_id, amount)
        logger.info(f"[WEBHOOK] db.update_balance вернул: {update_ok}")

        if not update_ok:
            logger.error(
                f"[WEBHOOK] ❌ update_balance вернул False для user={user_id}! "
                f"Возможно пользователь не зарегистрирован в БД. "
                f"Пробуем создать пользователя и повторить..."
            )
            await db.create_new_user(user_id)
            update_ok2 = await db.update_balance(user_id, amount)
            logger.info(f"[WEBHOOK] Повторный db.update_balance вернул: {update_ok2}")

        await db.log_payment(user_id, amount, "success", str(order_data), dict(data))

        # 5. Логика реферальной системы
        referrer_id = await db.get_referrer(user_id)
        logger.info(f"[WEBHOOK] referrer_id для user={user_id}: {referrer_id}")
        bonus_text = ""
        if referrer_id:
            bonus_amount = max(1, int(amount * 0.1))
            logger.info(f"[WEBHOOK] Начисляем реф. бонус {bonus_amount} руб. referrer={referrer_id}")
            await db.update_balance(referrer_id, bonus_amount)
            bonus_text = f"\n\n🎁 Ваш пригласитель получил бонус {bonus_amount} руб."

            asyncio.create_task(bot.api.messages.send(
                user_id=referrer_id,
                message=f"🎉 Вам начислен бонус {bonus_amount} руб. за пополнение баланса вашим другом!",
                random_id=0
            ))

        # 6. Запускаем анимацию в фоне и сразу отвечаем OK
        asyncio.create_task(process_delivery_animation(bot, user_id, amount, bonus_text))

        logger.info(f"✅ [WEBHOOK] Платеж {order_data} обработан. user={user_id}, amount={amount}")
        logger.info("="*60)
        return web.Response(text="OK", status=200)

    except Exception as e:
        logger.error(f"❌ [WEBHOOK] Неожиданная ошибка при обработке платежа: {e}\n{traceback.format_exc()}")
        return web.Response(text="Error", status=500)
