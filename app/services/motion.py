import logging
import traceback
from app.services.telegram_file import download_telegram_file, bytes_to_base64_data_uri, get_telegram_photo_url
from app.network import process_motion_control, upload_file_to_host
from app.services.generation import charge


async def background_motion_gen(bot, chat_id: int, char_photo_id: str, motion_video_id: str,
                                prompt: str, user_id: int, mode: str = "720p",
                                character_orientation: str = "image", cost_model: str = "kling_motion_720p"):
    """
    Фоновая задача для Motion Control.

    Args:
        mode: "720p" (5 ⚡) или "1080p" (10 ⚡)
        character_orientation: "image" (макс 10с) или "video" (макс 30с)
        cost_model: модель для зарядки ("kling_motion_720p" или "kling_motion_1080p")
    """
    try:
        logging.info(f"🎭 [MOTION TASK] Старт. Юзер: {user_id}, Mode: {mode}, Orientation: {character_orientation}")

        if not char_photo_id or not motion_video_id:
            logging.error(f"❌ Отсутствует файл. Фото: {char_photo_id}, Видео: {motion_video_id}")
            await bot.send_message(chat_id, "⚠️ Не удалось получить фото или видео. Попробуйте заново.")
            return

        # Скачиваем фото и видео из Telegram
        photo_bytes, photo_mime = await download_telegram_file(bot, char_photo_id)
        video_bytes, video_mime = await download_telegram_file(bot, motion_video_id)

        if not photo_bytes or not video_bytes:
            await bot.send_message(chat_id, "❌ Не удалось скачать фото или видео из Telegram. Попробуйте ещё раз.")
            return

        # Загружаем фото на 0x0.st
        logging.info(f"📷 Загрузка фото ({len(photo_bytes) / 1024:.1f} KB)...")
        char_url = await upload_file_to_host(photo_bytes, filename="character.jpg")
        if not char_url:
            char_url = bytes_to_base64_data_uri(photo_bytes, photo_mime)
            logging.warning("⚠️ 0x0.st недоступен для фото, используем base64")

        # Загружаем видео на 0x0.st
        logging.info(f"🎥 Загрузка видео ({len(video_bytes) / (1024 * 1024):.1f} MB)...")
        motion_url = await upload_file_to_host(video_bytes, filename="motion.mp4")
        if not motion_url:
            logging.error("❌ Не удалось загрузить видео на 0x0.st")
            await bot.send_message(chat_id, "❌ Ошибка загрузки видео. Попробуйте видео поменьше или позже.")
            return

        logging.info(f"🔗 Ссылки готовы. Отправка в Kling v2.6...")
        logging.info(f"  📷 Фото: {char_url[:80]}...")
        logging.info(f"  🎥 Видео: {motion_url[:80]}...")

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
        video_file = BufferedInputFile(result_bytes, filename=f"motion_{user_id}.mp4")

        await bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption="🎭 Motion Control готов!\nВаше фото ожило по видео-референсу.",
        )

        await charge(user_id, cost_model)
        logging.info(f"✅ [MOTION SUCCESS] Видео отправлено пользователю {user_id}")

    except Exception as e:
        logging.error(f"❌ [MOTION CRITICAL ERROR]: {e}")
        logging.error(traceback.format_exc())
        await bot.send_message(chat_id, "⚠️ Произошла ошибка при обработке видео. Генерация не списана.")