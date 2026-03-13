import logging
import traceback
import asyncio
import os
import subprocess
from app.services.telegram_file import download_telegram_file
from app.network import process_motion_control
from app.services.generation import charge


async def compress_video(video_bytes: bytes, user_id: int, quality: str = "medium") -> bytes:
    """
    Сжимает видео используя ffmpeg.
    """

    quality_presets = {
        "low": {"crf": 32, "preset": "fast"},
        "medium": {"crf": 28, "preset": "medium"},
        "high": {"crf": 23, "preset": "slow"}
    }

    params = quality_presets.get(quality, quality_presets["medium"])

    input_file = f"/tmp/motion_input_{user_id}.mp4"
    output_file = f"/tmp/motion_output_{user_id}.mp4"

    try:
        with open(input_file, 'wb') as f:
            f.write(video_bytes)

        original_size_mb = len(video_bytes) / (1024 * 1024)
        logging.info(f"📹 Исходное видео: {original_size_mb:.1f} MB. Сжимаем ({quality})...")

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

        await asyncio.wait_for(process.wait(), timeout=300)

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
        for f in [input_file, output_file]:
            try:
                os.remove(f)
            except:
                pass


async def save_video_to_telegram(video_bytes: bytes, user_id: int) -> str:
    """
    Сохраняет видео в Telegram через бота и возвращает file_id.
    Это позволит позже отправлять видео мгновенно без повторной загрузки.
    """
    from app.bot import bot
    from io import BytesIO

    try:
        logging.info(f"💾 Загрузка видео в Telegram (кэширование)...")

        video_file = BytesIO(video_bytes)
        video_file.name = f"motion_{user_id}.mp4"

        # Загружаем видео в приватный канал (или в чат с собой)
        # Используем временный чат для кэширования
        temp_message = await bot.send_video(
            chat_id=user_id,  # Отправляем самому пользователю в привате
            video=video_file,
            caption="🎬 Motion Control (кэшировано)",
        )

        file_id = temp_message.video.file_id
        logging.info(f"✅ Видео закэшировано в Telegram. File ID: {file_id[:20]}...")

        return file_id

    except Exception as e:
        logging.error(f"❌ Ошибка кэширования видео: {e}")
        return None


async def background_motion_gen(bot, chat_id: int, char_photo_id: str, motion_video_id: str,
                                prompt: str, user_id: int, mode: str = "720p",
                                character_orientation: str = "image", cost_model: str = "kling_motion_720p"):
    """
    Фоновая задача для Motion Control.
    """
    try:
        logging.info(f"🎭 [MOTION TASK] Старт. Юзер: {user_id}, Mode: {mode}, Orientation: {character_orientation}")

        if not char_photo_id or not motion_video_id:
            logging.error(f"❌ Отсутствует файл")
            await bot.send_message(chat_id, "⚠️ Не удалось получить фото или видео. Попробуйте заново.")
            return

        # Получаем информацию о файлах
        try:
            photo_file = await bot.get_file(char_photo_id)
            video_file = await bot.get_file(motion_video_id)
        except Exception as e:
            logging.error(f"❌ Ошибка получения информации о файлах: {e}")
            await bot.send_message(chat_id, "⚠️ Не удалось получить информацию о файлах.")
            return

        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            logging.error("❌ BOT_TOKEN не найден")
            await bot.send_message(chat_id, "⚠️ Ошибка конфигурации бота.")
            return

        char_url = f"https://api.telegram.org/file/bot{bot_token}/{photo_file.file_path}"
        motion_url = f"https://api.telegram.org/file/bot{bot_token}/{video_file.file_path}"

        logging.info(f"🔗 URLs готовы для API")

        # Отправляем в Motion Control API
        logging.info(f"📤 Отправка в Kling v2.6...")
        result_bytes, ext, result_url = await process_motion_control(
            prompt,
            char_url,
            motion_url,
            mode=mode,
            character_orientation=character_orientation
        )

        if not result_bytes:
            logging.error("❌ API вернуло пустой результат")
            await bot.send_message(chat_id, "❌ Не удалось создать видео.")
            return

        video_size_mb = len(result_bytes) / (1024 * 1024)
        logging.info(f"✅ Видео получено: {video_size_mb:.1f} MB")

        # Сжимаем видео если оно больше 5 MB
        if video_size_mb > 5:
            logging.info(f"📹 Сжимаем видео...")
            result_bytes = await compress_video(result_bytes, user_id, quality="medium")
            video_size_mb = len(result_bytes) / (1024 * 1024)
            logging.info(f"📹 После сжатия: {video_size_mb:.1f} MB")

        # КРИТИЧЕСКИ ВАЖНО: Кэшируем видео в Telegram
        logging.info(f"💾 Кэшируем видео в Telegram...")
        file_id = await save_video_to_telegram(result_bytes, user_id)

        if not file_id:
            logging.error("❌ Не удалось кэшировать видео")
            await bot.send_message(chat_id, "❌ Ошибка при сохранении видео.")
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
                    logging.info(f"✅ [MOTION SUCCESS] Баланс списан")
                except Exception as e:
                    logging.error(f"❌ Ошибка при списании баланса: {e}")
                    await bot.send_message(chat_id, f"⚠️ Видео отправлено, но ошибка при списании баланса")

                return

            except Exception as e:
                error_msg = str(e).lower()
                logging.error(f"❌ Ошибка отправки (попытка {attempt}): {e}")

                if "invalid" in error_msg or "forbidden" in error_msg or "not found" in error_msg:
                    logging.error(f"��� Критическая ошибка, прекращаем попытки")
                    await bot.send_message(chat_id, f"❌ Ошибка: видео не может быть отправлено")
                    return

                if attempt == max_retries:
                    logging.error(f"❌ Не удалось отправить видео после {max_retries} попыток")
                    await bot.send_message(chat_id, f"❌ Не удалось отправить видео. Попробуйте позже.")
                    return

                logging.info(f"⏳ Ожидание {retry_delay} сек...")
                await asyncio.sleep(retry_delay)

    except Exception as e:
        logging.error(f"❌ [MOTION CRITICAL ERROR]: {e}")
        logging.error(traceback.format_exc())
        try:
            await bot.send_message(chat_id, f"⚠️ Критическая ошибка: {str(e)[:100]}")
        except:
            logging.error("❌ Не удалось отправить сообщение об ошибке")