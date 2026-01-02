from aiogram import Router, types, F
import database as db

router = Router()


@router.message(F.text == "👤 Мой баланс")
async def balance(message: types.Message):
    user_id = message.from_user.id

    # 1. Исправлено: добавлен await
    bal = await db.get_balance(user_id)

    # 2. Исправлено: добавлен await
    ref_count = await db.get_referrals_count(user_id)

    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    # 3. Переписано на HTML (более стабильно для aiogram 3.x)
    text = (
        f"👤 <b>Ваш профиль</b>\n"
        f"┣ ID: <code>{user_id}</code>\n"
        f"┗ Баланс: <b>{bal}</b> ⚡\n\n"
        f"👥 <b>Приглашено друзей:</b> <code>{ref_count}</code>\n\n"
        f"🎁 <b>Реферальная программа:</b>\n"
        f"Получайте <b>10%</b> от покупок друзей!\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"<i>Нажмите на ссылку, чтобы скопировать.</i>"
    )

    await message.answer(
        text,
        parse_mode="HTML",  # Указываем HTML явно
        disable_web_page_preview=True  # Чтобы ссылка не создавала огромное окно предпросмотра
    )