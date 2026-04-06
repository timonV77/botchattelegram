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
        logger.warning("⚠️ VK_PRODAMUS_KEY не задан. Проверка подписи пропущена.")
        return True
    
    if not received_signature:
        logger.error("⛔ Подпись отсутствует в запросе (Sign пуст). secret_key задан, но подпись не пришла.")
        return False

    # Сортируем ключи и формируем строку данных (аналогично PHP http_build_query)
    sorted_keys = sorted(data.keys())
    filtered_data = {k: data[k] for k in sorted_keys if k != 'Sign'}
    data_string = urllib.parse.urlencode(filtered_data)
    
    computed_signature = hmac.new(
        secret_key.encode('utf-8'),
        data_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    match = hmac.compare_digest(computed_signature.lower(), received_signature.lower())
    
    if not match:
        logger.error(
            f"⛔ ПОДПИСЬ НЕ СОВПАДАЕТ!\n"
            f"  Полученная:  {received_signature}\n"
            f"  Вычисленная: {computed_signature}\n"
            f"  Строка для подписи ({len(data_string)} символов): {data_string[:500]}...\n"
            f"  Ключи данных: {list(filtered_data.keys())}"
        )
    else:
        logger.info(f"✅ Подпись верна: {received_signature[:16]}...")
    
    return match


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
    logger.info("=" * 60)
    logger.info(f"[WEBHOOK] ====== НОВЫЙ ВХОДЯЩИЙ ПЛАТЁЖ ======")
    logger.info(f"[WEBHOOK] Метод: {request.method}, Путь: {request.path}")
    logger.info(f"[WEBHOOK] IP отправителя: {request.remote}")
    logger.info(f"[WEBHOOK] Заголовки: {dict(request.headers)}")

    bot: Bot = request.app.get('bot')
    if not bot:
        logger.error("❌ [WEBHOOK] КРИТИЧНО: Объект Bot не найден в request.app! Платёж НЕ МОЖЕТ быть обработан.")
        return web.Response(text="Internal Error", status=500)

    # ─── 1. Получаем данные ──────────────────────────────────────────────
    data = {}
    raw_body = b""
    try:
        raw_body = await request.read()
        logger.info(f"[WEBHOOK] Raw body ({len(raw_body)} bytes): {raw_body[:2000]}")

        post_data = await request.post()
        if post_data:
            data.update(post_data)
            logger.info(f"[WEBHOOK] Распарсено как form-data, ключи: {list(data.keys())}")
            logger.info(f"[WEBHOOK] form-data значения: {dict(data)}")

        if not data:
            try:
                json_data = await request.json()
                if json_data:
                    data.update(json_data)
                    logger.info(f"[WEBHOOK] Распарсено как JSON, ключи: {list(data.keys())}")
                    logger.info(f"[WEBHOOK] JSON значения: {dict(data)}")
            except Exception as je:
                logger.warning(f"[WEBHOOK] JSON parse failed: {je}")
    except Exception as e:
        logger.error(f"⚠️ [WEBHOOK] Не удалось распарсить тело запроса: {e}\n{traceback.format_exc()}")

    if not data:
        logger.error(
            f"[WEBHOOK] ❌ ДАННЫЕ ПУСТЫ — тело запроса не распознано!\n"
            f"  Content-Type: {request.content_type}\n"
            f"  Raw body: {raw_body[:500]}"
        )
        return web.Response(text="Bad Request", status=400)

    # ─── 2. Проверка подписи ─────────────────────────────────────────────
    received_sign = request.headers.get("Sign") or data.get("Sign")
    logger.info(f"[WEBHOOK] Подпись из заголовка: {request.headers.get('Sign')!r}")
    logger.info(f"[WEBHOOK] Подпись из data: {data.get('Sign')!r}")
    logger.info(f"[WEBHOOK] VK_PRODAMUS_KEY задан: {bool(settings.vk_prodamus_key)}, длина: {len(settings.vk_prodamus_key) if settings.vk_prodamus_key else 0}")

    sig_ok = verify_vk_signature(data, received_sign, settings.vk_prodamus_key)
    logger.info(f"[WEBHOOK] Результат проверки подписи: {sig_ok}")

    if not sig_ok:
        logger.error(
            f"⛔️ [WEBHOOK] ПОДПИСЬ НЕВАЛИДНА! Платёж может быть поддельным.\n"
            f"  Полученная подпись: {received_sign!r}\n"
            f"  ⚠️ ВРЕМЕННО РАЗРЕШЕНО ДЛЯ ДЕБАГА — платёж будет обработан"
        )

    # ─── 3. Разбираем поля платежа ───────────────────────────────────────
    payment_status = data.get("payment_status")
    order_data = data.get("order_num") or data.get("order_id")
    reported_sum = data.get("sum") or data.get("amount") or 0

    logger.info(
        f"[WEBHOOK] === ПОЛЯ ПЛАТЕЖА ===\n"
        f"  payment_status = {payment_status!r}\n"
        f"  order_num      = {data.get('order_num')!r}\n"
        f"  order_id       = {data.get('order_id')!r}\n"
        f"  sum            = {data.get('sum')!r}\n"
        f"  amount         = {data.get('amount')!r}\n"
        f"  customer_phone = {data.get('customer_phone')!r}\n"
        f"  customer_email = {data.get('customer_email')!r}\n"
        f"  date           = {data.get('date')!r}\n"
        f"  products       = {data.get('products')!r}"
    )

    if payment_status != "success":
        logger.warning(
            f"[WEBHOOK] ⚠️ payment_status={payment_status!r} — НЕ 'success'!\n"
            f"  Платёж ИГНОРИРУЕТСЯ. Средства НЕ будут зачислены.\n"
            f"  order_data={order_data!r}, reported_sum={reported_sum!r}"
        )
        return web.Response(text="Ignored", status=200)

    if not order_data:
        logger.error(
            f"[WEBHOOK] ❌ order_num/order_id ОТСУТСТВУЕТ в данных!\n"
            f"  Невозможно определить пользователя. Средства НЕ зачислены.\n"
            f"  Все ключи в data: {list(data.keys())}"
        )
        return web.Response(text="Ignored", status=200)

    try:
        # ─── 3a. Парсим user_id и amount из order_data ───────────────────
        p = str(order_data).split("_")
        if len(p) >= 2:
            user_id = int(p[0])
            amount = int(p[1])
            logger.info(f"[WEBHOOK] ✅ Разобран order_data: user_id={user_id}, amount={amount}")
        else:
            vk_user_id = data.get("vk_user_id")
            logger.warning(
                f"[WEBHOOK] ⚠️ order_data нестандартный формат!\n"
                f"  order_data={order_data!r} (ожидался формат 'USER_ID_AMOUNT')\n"
                f"  Пробуем fallback через vk_user_id={vk_user_id!r}"
            )
            if vk_user_id and str(vk_user_id).isdigit():
                user_id = int(vk_user_id)
                amount = int(float(reported_sum))
                logger.info(f"[WEBHOOK] Fallback: user_id={user_id}, amount={amount}")
            else:
                logger.error(
                    f"❌ [WEBHOOK] НЕ УДАЛОСЬ ОПРЕДЕЛИТЬ ПОЛЬЗОВАТЕЛЯ!\n"
                    f"  order_data={order_data!r}, vk_user_id={vk_user_id!r}\n"
                    f"  reported_sum={reported_sum!r}\n"
                    f"  💸 СРЕДСТВА НЕ ЗАЧИСЛЕНЫ — ТРЕБУЕТСЯ РУЧНОЕ РАЗБИРАТЕЛЬСТВО"
                )
                return web.Response(text="Invalid data", status=400)

        # ─── 3b. Проверка суммы ──────────────────────────────────────────
        try:
            reported_sum_int = int(float(reported_sum))
            if reported_sum_int != amount:
                logger.warning(
                    f"[WEBHOOK] ⚠️ НЕСОВПАДЕНИЕ СУММ!\n"
                    f"  Сумма из order_data: {amount} руб.\n"
                    f"  Сумма из reported_sum (sum/amount поле): {reported_sum_int} руб.\n"
                    f"  Будет зачислена сумма из order_data: {amount} руб."
                )
        except (ValueError, TypeError):
            logger.warning(f"[WEBHOOK] ⚠️ Не удалось распарсить reported_sum: {reported_sum!r}")

        # ─── 3c. Проверка дубликатов ─────────────────────────────────────
        try:
            from asyncpg import Pool
            pool = db._pool
            if pool:
                async with pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT id, created_at, amount FROM payment_logs WHERE order_id = $1 AND status = 'success'",
                        str(order_data)
                    )
                    if existing:
                        logger.error(
                            f"[WEBHOOK] ⚠️ ДУБЛИКАТ ПЛАТЕЖА!\n"
                            f"  order_id={order_data!r} уже обработан ранее:\n"
                            f"  payment_log_id={existing['id']}, дата={existing['created_at']}, сумма={existing['amount']}\n"
                            f"  ❌ Повторное зачисление ОТМЕНЕНО для защиты от двойного списания"
                        )
                        return web.Response(text="Duplicate", status=200)
                    else:
                        logger.info(f"[WEBHOOK] ✅ Дубликат не найден — order_id={order_data!r} новый")
            else:
                logger.warning("[WEBHOOK] ⚠️ DB pool недоступен — проверка дубликатов ПРОПУЩЕНА")
        except Exception as dup_err:
            logger.warning(f"[WEBHOOK] ⚠️ Ошибка проверки дубликатов: {dup_err}")

        # ─── 4. Читаем баланс ДО зачисления ─────────────────────────────
        balance_before = None
        try:
            balance_before = await db.get_balance(user_id)
            logger.info(f"[WEBHOOK] 💰 Баланс ДО зачисления: user={user_id}, balance={balance_before} руб.")
        except Exception as bal_err:
            logger.error(f"[WEBHOOK] ❌ Не удалось прочитать баланс ДО зачисления: {bal_err}")

        # ─── 5. ЗАЧИСЛЕНИЕ в базу ────────────────────────────────────────
        logger.info(f"[WEBHOOK] >>> Вызываем db.update_balance(user_id={user_id}, amount={amount})")
        update_ok = await db.update_balance(user_id, amount)
        logger.info(f"[WEBHOOK] <<< db.update_balance вернул: {update_ok}")

        if not update_ok:
            logger.error(
                f"[WEBHOOK] ❌ update_balance ВЕРНУЛ False для user={user_id}!\n"
                f"  Возможные причины:\n"
                f"  1. Пользователь НЕ зарегистрирован в таблице users\n"
                f"  2. Ошибка подключения к БД\n"
                f"  3. UPDATE вернул 0 строк\n"
                f"  Пробуем создать пользователя и повторить..."
            )
            # Создаём пользователя
            create_ok = await db.create_new_user(user_id)
            logger.info(f"[WEBHOOK] db.create_new_user({user_id}) вернул: {create_ok}")

            # Повторная попытка зачисления
            update_ok2 = await db.update_balance(user_id, amount)
            logger.info(f"[WEBHOOK] Повторный db.update_balance вернул: {update_ok2}")

            if not update_ok2:
                logger.error(
                    f"[WEBHOOK] ❌❌ КРИТИЧЕСКАЯ ОШИБКА: Повторное зачисление ТОЖЕ ПРОВАЛИЛОСЬ!\n"
                    f"  user_id={user_id}, amount={amount}\n"
                    f"  💸 СРЕДСТВА НЕ ЗАЧИСЛЕНЫ ПОЛЬЗОВАТЕЛЮ!\n"
                    f"  ТРЕБУЕТСЯ РУЧНОЕ ВМЕШАТЕЛЬСТВО!"
                )

        # ─── 5a. Читаем баланс ПОСЛЕ зачисления ─────────────────────────
        try:
            balance_after = await db.get_balance(user_id)
            logger.info(
                f"[WEBHOOK] 💰 Баланс ПОСЛЕ зачисления: user={user_id}, balance={balance_after} руб.\n"
                f"  Было: {balance_before} → Стало: {balance_after} (дельта: +{amount})\n"
                f"  Ожидаемый баланс: {(balance_before or 0) + amount}"
            )
            expected = (balance_before or 0) + amount
            if balance_after != expected:
                logger.warning(
                    f"[WEBHOOK] ⚠️ БАЛАНС НЕ СОВПАДАЕТ С ОЖИДАЕМЫМ!\n"
                    f"  Ожидали: {expected}, Получили: {balance_after}\n"
                    f"  Возможно: параллельное списание, GREATEST(0, ...) ограничение, или ошибка"
                )
        except Exception as bal_err:
            logger.error(f"[WEBHOOK] ❌ Не удалось прочитать баланс ПОСЛЕ зачисления: {bal_err}")

        # ─── 6. Лог платежа в БД ────────────────────────────────────────
        try:
            await db.log_payment(user_id, amount, "success", str(order_data), dict(data))
            logger.info(f"[WEBHOOK] ✅ Платёж записан в payment_logs: order={order_data}")
        except Exception as log_err:
            logger.error(
                f"[WEBHOOK] ❌ ОШИБКА ЗАПИСИ в payment_logs!\n"
                f"  user={user_id}, amount={amount}, order={order_data}\n"
                f"  Ошибка: {log_err}\n{traceback.format_exc()}"
            )

        # ─── 7. Реферальная система ──────────────────────────────────────
        referrer_id = await db.get_referrer(user_id)
        logger.info(f"[WEBHOOK] referrer_id для user={user_id}: {referrer_id}")
        bonus_text = ""
        if referrer_id:
            bonus_amount = max(1, int(amount * 0.1))
            logger.info(f"[WEBHOOK] Начисляем реф. бонус {bonus_amount} руб. referrer={referrer_id}")
            ref_ok = await db.update_balance(referrer_id, bonus_amount)
            if not ref_ok:
                logger.error(f"[WEBHOOK] ❌ Реферальный бонус НЕ ЗАЧИСЛЕН referrer={referrer_id}!")
            bonus_text = f"\n\n🎁 Ваш пригласитель получил бонус {bonus_amount} руб."

            asyncio.create_task(bot.api.messages.send(
                user_id=referrer_id,
                message=f"🎉 Вам начислен бонус {bonus_amount} руб. за пополнение баланса вашим другом!",
                random_id=0
            ))

        # ─── 8. Запускаем анимацию и отвечаем OK ─────────────────────────
        asyncio.create_task(process_delivery_animation(bot, user_id, amount, bonus_text))

        logger.info(
            f"✅ [WEBHOOK] ====== ПЛАТЁЖ ОБРАБОТАН УСПЕШНО ======\n"
            f"  order_data={order_data}\n"
            f"  user_id={user_id}\n"
            f"  amount={amount}\n"
            f"  balance: {balance_before} → {balance_after if 'balance_after' in dir() else '?'}"
        )
        logger.info("=" * 60)
        return web.Response(text="OK", status=200)

    except Exception as e:
        logger.error(
            f"❌ [WEBHOOK] НЕОБРАБОТАННАЯ ОШИБКА при обработке платежа!\n"
            f"  order_data={order_data!r}\n"
            f"  reported_sum={reported_sum!r}\n"
            f"  Ошибка: {e}\n{traceback.format_exc()}"
        )
        return web.Response(text="Error", status=500)
