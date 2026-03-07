import logging
import asyncio
import traceback
from app.services.telegram_file import get_telegram_photo_url
from app.network import process_motion_control
from app.services.generation import charge
import database as db

async def background_motion_gen(bot, chat_id: int, char_photo_id: str, motion_video_id: str, prompt: str, user_id: int):
    """
    Принцип работы:
    1. Берем фото лица (char_photo_id)
    2. Берем видео с движением (motion_video_id)
    3. Передаем их в Kling v2.6 для переноса движения на лицо.
    """
    try:
        logging.info(f"🎭 [MOTION TASK] Старт. Юзер: {user_id}")

        # Проверка на наличие ID, чтобы не упасть с ошибкой Pydantic
        if not char_photo_id or not motion_video_id:
            logging.error(f"❌ Ошибка: отсутствует один из файлов. Фото: {char_photo_id}, Видео: {motion_video_id}")
            await bot.send_message(chat_id, "⚠️ Не удалось получить фото или видео. Попробуйте загрузить их заново.")
            return

        # 1. Получаем ссылки из Telegram
        # Важно: Сначала получаем фото лица
        char_url = await get_telegram_photo_url(bot, char_photo_id)
        # Затем получаем видео движения
        motion_url = await get_telegram_photo_url(bot, motion_video_id)

        if not char_url or not motion_url:
            await bot.send_message(chat_id, "❌ Ошибка при генерации ссылок. Попробуйте еще раз.")
            return

        logging.info(f"🔗 Ссылки готовы. Отправка в Kling v2.6...")

        # 2. Вызываем генерацию
        # Функция process_motion_control в network.py должна принимать их именно в этом порядке
        _, _, result_url = await process_motion_control(prompt, char_url, motion_url)

        if not result_url:
            logging.error("❌ API вернуло пустой результат")
            await bot.send_message(chat_id, "❌ Не удалось создать видео. Попробуйте другой промпт или видео-референс.")
            return

        # 3. Извлекаем URL и отправляем
        final_v_url = result_url.get("url") if isinstance(result_url, dict) else result_url

        await bot.send_video(
            chat_id=chat_id,
            video=str(final_v_url),
            caption="🎭 **Motion Control готов!**\nВаше фото ожило по видео-референсу.",
        )

        # 4. Списание средств
        await charge(user_id, "kling_motion")
        logging.info(f"✅ [MOTION SUCCESS] Видео отправлено пользователю {user_id}")

    except Exception as e:
        logging.error(f"❌ [MOTION CRITICAL ERROR]: {e}")
        logging.error(traceback.format_exc())
        await bot.send_message(chat_id, "⚠️ Произошла ошибка при обработке видео.")