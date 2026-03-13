import logging
import traceback
import asyncio
import os
import subprocess
from io import BytesIO
from app.network import process_motion_control
from app.services.generation import charge


async def compress_video(video_bytes: bytes, user_id: int, quality: str = "medium") -> bytes:
    """
    Сжимает видео используя ffmpeg.

    Args:
        video_bytes: Исходное видео в байтах
        user_id: ID пользователя (для временного файла)
        quality: "low" (60%), "medium" (75%), "high" (85%)

    Returns:
        Сжатое видео в байтах
    """

    quality_presets = {
        "low": {"crf": 32, "preset": "fast"},  # Сильное сжатие
        "medium": {"crf": 28, "preset": "medium"},  # Среднее сжатие
        "high": {"crf": 23, "preset": "slow"}  # Слабое сжатие
    }

    params = quality_presets.get(quality, quality_presets["medium"])

    input_file = f"/tmp/motion_input_{user_id}.mp4"
    output_file = f"/tmp/motion_output_{user_id}.mp4"

    try:
        # Записываем входное видео
        with open(input_file, 'wb') as f:
            f.write(video_bytes)

        original_size_mb = len(video_bytes) / (1024 * 1024)
        logging.info(f"📹 Исходное видео: {original_size_mb:.1f} MB. Сжимаем ({quality})...")

        # Сжимаем видео ffmpeg
        cmd = [
            'ffmpeg',
            '-i', input_file,
            '-c:v', 'libx264',
            '-crf', str(params['crf']),
            '-preset', params['preset'],
            '-c:a', 'aac',
            '-b:a', '128k',
            '-y',
            output_file
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )

        await asyncio.wait_for(process.wait(), timeout=300)  # 5 минут макс

        # Читаем сжатое видео
        with open(output_file, 'rb') as f:
            compressed_bytes = f.read()

        compressed_size_mb = len(compressed_bytes) / (1024 * 1024)
        ratio = (1 - len(compressed_bytes) / len(video_bytes)) * 100

        logging.info(f"✅ Видео сжато: {compressed_size_mb:.1f} MB (экономия {ratio:.1f}%)")

        return compressed_bytes

    except FileNotFoundError:
        logging.warning(f"⚠️ ffmpeg не установлен, отправляем оригинальное видео")
        return video_bytes
    except Exception as e:
        logging.error(f"❌ Ошибка сжатия видео: {e}")
        return video_bytes
    finally:
        # Удаляем временные файлы
        for f in [input_file, output_file]:
            try:
                os.remove(f)
            except:
                pass


async def save_video_to_telegram(bot, video_bytes: bytes, user_id: int) -> str:
    """
    Сохраняет видео в Telegram через бота и возвращает file_id.
    Это позволит позже отправлять видео мгновенно без повторной загрузки.

    Args:
        bot: Экземпляр бота
        video_bytes: Байты видео
        user_id: ID пользователя

    Returns:
        file_id видео или None
    """
    try:
        logging.info(f"💾 Загрузка видео в Telegram (кэширование)...")

        video_file = BytesIO(video_bytes)
        video_file.name = f"motion_{user_id}.mp4"

        # Загружаем видео в приватный чат с пользователем
        temp_message = await bot.send_video(
            chat_id=user_id,
            video=video_file,
            caption="🎬 Motion Control (кэшировано)",
        )

        file_id = temp_message.video.file_id
        logging.info(f"✅ Видео закэшировано в Telegram. File ID: {file_id[:20]}...")

        return file_id

    except Exception as e:
        logging.error(f"❌ Ошибка кэширования видео: {e}")
        logging.error(traceback.format_exc())
        return None


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
            logging.error(f"❌ Ошибка получения информации о файлах: {e}")
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

        video_size_mb = len(result_bytes) / (1024 * 1024)
        logging.info(f"✅ Видео получено от API: {video_size_mb:.1f} MB")

        # Сжимаем видео если оно больше 5 MB
        if video_size_mb > 5:
            logging.info(f"📹 Видео больше 5 MB, сжимаем...")
            result_bytes = await compress_video(result_bytes, user_id, quality="medium")
            video_size_mb = len(result_bytes) / (1024 * 1024)
            logging.info(f"📹 Размер после сжатия: {video_size_mb:.1f} MB")

        # КРИТИЧЕСКИ ВАЖНО: Кэшируем видео в Telegram
        logging.info(f"💾 Кэшируем видео в Telegram...")
        file_id = await save_video_to_telegram(bot, result_bytes, user_id)

        if not file_id:
            logging.error("❌ Не удалось кэшировать видео")
            await bot.send_message(chat_id, "❌ Ошибка при сохранении видео. Попробуйте позже.")
            return

        # Теперь отправляем видео по file_id (МГНОВЕННО!)
        max_retries = 3
        retry_delay = 5

        for attempt in range(1, max_retries + 1):
            try:
                logging.info(f"📤 Отправка видео по file_id (попытка {attempt}/{max_retries})...")

                # Отправляем ПО FILE_ID - это мгновенно!
                message = await bot.send_video(
                    chat_id=chat_id,
                    video=file_id,
                    caption="🎭 Motion Control готов!\nВаше фото ожило по видео-референсу.",
                )

                logging.info(f"✅ Видео успешно отправлено! Message ID: {message.message_id}")

                # Списываем баланс только после успешной отправки
                try:
                    await charge(user_id, cost_model)
                    logging.info(f"✅ [MOTION SUCCESS] Баланс списан для пользователя {user_id}")
                except Exception as e:
                    logging.error(f"❌ Ошибка при списании баланса: {e}")
                    await bot.send_message(chat_id, f"⚠️ Видео отправлено, но ошибка при списании баланса")

                return  # Выходим при успехе

            except Exception as e:
                error_msg = str(e).lower()
                logging.error(f"❌ Ошибка при отправке видео (попытка {attempt}): {e}")

                # Если это критическая ошибка — не повторяем
                if "invalid" in error_msg or "forbidden" in error_msg or "not found" in error_msg:
                    logging.error(f"❌ Критическая ошибка Telegram, прекращаем попытки")
                    await bot.send_message(chat_id, f"❌ Ошибка Telegram: видео не может быть отправлено")
                    return

                # Если это последняя попытка
                if attempt == max_retries:
                    logging.error(f"❌ Не удалось отправить видео после {max_retries} попыток")
                    await bot.send_message(chat_id, f"❌ Не удалось отправить видео. Попробуйте позже.")
                    return

                # Ждем перед следующей попыткой
                wait_time = retry_delay * attempt
                logging.info(f"⏳ Ожидание {wait_time} сек перед следующей попыткой...")
                await asyncio.sleep(wait_time)

    except Exception as e:
        logging.error(f"❌ [MOTION CRITICAL ERROR]: {e}")
        logging.error(traceback.format_exc())
        try:
            await bot.send_message(chat_id, f"⚠️ Критическая ошибка: {str(e)[:100]}")
        except:
            logging.error("❌ Даже сообщение об ошибке не удалось отправить")