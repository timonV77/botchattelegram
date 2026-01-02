from aiogram import Router, types, F
import database as db

router = Router()


@router.message(F.text == "👤 Мой баланс")
async def balance(message: types.Message):
    user_id = message.from_user.id
    bal = db.get_balance(user_id)
    ref_count = db.get_referrals_count(user_id)  # Счетчик из БД

    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

    text = (
        f"👤 **Ваш профиль**\n"
        f"┣ ID: `{user_id}`\n"
        f"┗ Баланс: **{bal}** ⚡\n\n"
        f"👥 **Приглашено друзей:** `{ref_count}`\n\n"
        f"🎁 **Рeферальная программа:**\n"
        f"Получайте **10%** от покупок друзей!\n\n"
        f"🔗 **Ваша ссылка:**\n`{ref_link}`\n\n"
        f"_Нажмите на ссылку, чтобы скопировать._"
    )

    await message.answer(
        text,
        parse_mode="Markdown",
        timeout=60  # увеличиваем таймаут до 60 секунд
    )
