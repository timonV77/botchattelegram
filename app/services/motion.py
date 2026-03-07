import logging
import asyncio
import traceback
from app.services.telegram_file import get_telegram_photo_url
from app.network import process_motion_control
from app.services.generation import charge
import database as db

async def background_motion_gen(bot, chat_id: int, char_photo_id: str, motion_video_id: str, prompt: str, user_id: int):
    try:
        logging.info(f"🎭 [MOTION TASK] Старт. Юзер: {user_id}")

        if not char_photo_id or not motion_video_id:
            logging.error(f"❌ Отсутствует файл. Фото: {char_photo_id}, Видео: {motion_video_id}")
            await bot.send_message(chat_id, "⚠️ Не удалось получить фото или видео. Попробуйте заново.")
            return

        char_url = await get_telegram_photo_url(bot, char_photo_id)
        motion_url = await get_telegram_photo_url(bot, motion_video_id)

        if not char_url or not motion_url:
            await bot.send_message(chat_id, "❌ Ошибка при генерации ссылок. Попробуйте еще раз.")
            return

        logging.info(f"🔗 Ссылки готовы. Отправка в Kling v2.6...")
        logging.info(f"  📷 Фото: {char_url[:80]}...")
        logging.info(f"  🎥 Видео: {motion_url[:80]}...")

        _, _, result_url = await process_motion_control(prompt, char_url, motion_url)

        if not result_url:
            logging.error("❌ API вернуло пустой результат")
            await bot.send_message(chat_id, "❌ Не удалось создать видео. Попробуйте другой промпт или видео-референс.")
            return

        final_v_url = result_url.get("url") if isinstance(result_url, dict) else result_url

        await bot.send_video(
            chat_id=chat_id,
            video=str(final_v_url),
            caption="🎭 **Motion Control готов!**\nВаше фото ожило по видео-референсу.",
        )

        # ✅ Списание ПОСЛЕ успешной отправки
        await charge(user_id, "kling_motion")
        logging.info(f"✅ [MOTION SUCCESS] Видео отправлено пользователю {user_id}")

    except Exception as e:
        logging.error(f"❌ [MOTION CRITICAL ERROR]: {e}")
        logging.error(traceback.format_exc())
        await bot.send_message(chat_id, "⚠️ Произошла ошибка при обработке видео. Генерация не списана.")