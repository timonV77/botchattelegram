import logging
import traceback
import asyncio
import os
from app.services.telegram_file import download_telegram_file, bytes_to_base64_data_uri
from app.network import process_motion_control
from app.services.generation import charge


async def background_motion_gen(bot, chat_id: int, char_photo_id: str, motion_video_id: str,
                                prompt: str, user_id: int, mode: str = "720p",
                                character_orientation: str = "image", cost_model: str = "kling_motion_720p"):
    """
    Фоновая задача для Motion Control.
    Использует прямые URL из Telegram вместо загрузки на сторонние хостинги.
    """
    try:
        logging.info(f"🎭 [MOTION TASK] Старт. Юзер: {user_id}, Mode: {mode}, Orientation: {character_orientation}")

        if not char_photo_id or not motion_video_id:
            logging.error(f"❌ Отсутствует файл. Фото: {char_photo_id}, Видео: {motion_video_id}")
            await bot.send_message(chat_id, "⚠️ Не удалось получить фото или видео. Попробуйте заново.")
            return

        # Получаем информацию о файлах
        try:
            photo_file = await bot.get_file(char_photo_id)
            video_file = await bot.get_file(motion_video_id)
        except Exception as e:
            logging.error(f"❌ Ошиб��а получения информации о файлах: {e}")
            await bot.send_message(chat_id, "⚠️ Не удалось получить информацию о файлах. Попробуйте заново.")
            return

        # Формируем прямые URL из Telegram
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            logging.error("❌ BOT_TOKEN не найден")
            await bot.send_message(chat_id, "⚠️ Ошибка конфигурации бота.")
            return

        char_url = f"https://api.telegram.org/file/bot{bot_token}/{photo_file.file_path}"
        motion_url = f"https://api.telegram.org/file/bot{bot_token}/{video_file.file_path}"

        logging.info(f"🔗 Получены прямые URL из Telegram:")
        logging.info(f"  📷 Фото: {char_url[:80]}...")
        logging.info(f"  🎥 Видео: {motion_url[:80]}...")

        # Отправляем в Motion Control API
        logging.info(f"📤 Отправка в Kling v2.6 Motion Control...")
        result_bytes, ext, result_url = await process_motion_control(
            prompt,
            char_url,
            motion_url,
            mode=mode,
            character_orientation=character_orientation
        )

        if not result_bytes:
            logging.error("❌ API вернуло пустой результат")
            await bot.send_message(chat_id, "❌ Не удалось создать видео. Попробуйте другой промпт или видео-референс.")
            return

        from aiogram.types import BufferedInputFile
        video_file_output = BufferedInputFile(result_bytes, filename=f"motion_{user_id}.mp4")

        await bot.send_video(
            chat_id=chat_id,
            video=video_file_output,
            caption="🎭 Motion Control готов!\nВаше фото ожило по видео-референсу.",
        )

        await charge(user_id, cost_model)
        logging.info(f"✅ [MOTION SUCCESS] Видео отправлено пользователю {user_id}")

    except Exception as e:
        logging.error(f"❌ [MOTION CRITICAL ERROR]: {e}")
        logging.error(traceback.format_exc())
        await bot.send_message(chat_id, "⚠️ Произошла ошибка при обработке видео. Генерация не списана.")