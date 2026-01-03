import asyncio
from aiogram import Router, types, F
import database as db

router = Router()


@router.message(F.text.lower().contains("баланс"))
async def balance(message: types.Message):
    user_id = message.from_user.id

    try:
        # Оптимизация: запускаем запросы к БД параллельно
        # Это значительно экономит время ожидания
        tasks = [
            db.get_balance(user_id),
            db.get_referrals_count(user_id),
            message.bot.get_me()
        ]

        # Ждем выполнения всех задач сразу
        bal, ref_count, bot_info = await asyncio.gather(*tasks)

        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"

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
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    except Exception as e:
        # Если что-то пошло не так, бот не просто молчит, а логирует ошибку
        import logging
        logging.error(f"Ошибка в балансе для {user_id}: {e}")
        await message.answer("⚠️ Произошла ошибка при загрузке профиля. Попробуйте чуть позже.")