import logging
import traceback
import asyncio
import os
from io import BytesIO

# Импорты aiogram
from aiogram.types import BufferedInputFile

# Импорты из твоего проекта
from app.network import process_motion_control
from app.services.generation import charge


async def compress_video(video_bytes: bytes, user_id: int, quality: str = "medium") -> bytes:
    """
    Сжимает видео используя ffmpeg с низким приоритетом (nice), чтобы не вешать бота.
    """
    quality_presets = {
        "low": {"crf": 32, "preset": "faster"},
        "medium": {"crf": 28, "preset": "medium"},
        "high": {"crf": 23, "preset": "slow"}
    }

    params = quality_presets.get(quality, quality_presets["medium"])
    input_file = f"/tmp/motion_input_{user_id}.mp4"
    output_file = f"/tmp/motion_output_{user_id}.mp4"

    try:
        with open(input_file, 'wb') as f:
            f.write(video_bytes)

        # Проверяем наличие ffmpeg перед запуском
        cmd = [
            'nice', '-n', '15',
            'ffmpeg', '-i', input_file,
            '-c:v', 'libx264', '-crf', str(params['crf']),
            '-preset', params['preset'],
            '-c:a', 'aac', '-b:a', '128k',
            '-y', output_file
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )

        await asyncio.wait_for(process.wait(), timeout=300)

        if os.path.exists(output_file):
            with open(output_file, 'rb') as f:
                return f.read()
        return video_bytes

    except Exception as e:
        logging.error(f"❌ Ошибка сжатия: {e}")
        return video_bytes
    finally:
        for f_path in [input_file, output_file]:
            if os.path.exists(f_path):
                try:
                    os.remove(f_path)
                except:
                    pass


async def save_video_to_telegram(bot, video_bytes: bytes, user_id: int) -> str:
    """Кэширует видео в Telegram и возвращает file_id."""
    try:
        video_file = BufferedInputFile(video_bytes, filename=f"motion_{user_id}.mp4")

        # Отправляем видео пользователю напрямую (это и будет кэшированием)
        temp_message = await bot.send_video(
            chat_id=user_id,
            video=video_file,
            caption="🎬 Ваше видео готово!",
        )
        return temp_message.video.file_id
    except Exception as e:
        logging.error(f"❌ Ошибка отправки/кэширования: {e}")
        return None


async def background_motion_gen(bot, chat_id: int, char_photo_id: str, motion_video_id: str,
                                prompt: str, user_id: int, mode: str = "720p",
                                character_orientation: str = "image", cost_model: str = "kling_motion_720p"):
    """Оптимизированная фоновая задача для Kling Motion."""
    try:
        logging.info(f"🎭 [MOTION] Старт задачи для {user_id}")

        # 1. Получаем ссылки на файлы (используем bot.token, так как os.getenv может подвести)
        try:
            photo_file = await asyncio.wait_for(bot.get_file(char_photo_id), timeout=30)
            video_file = await asyncio.wait_for(bot.get_file(motion_video_id), timeout=30)
        except Exception as e:
            logging.error(f"❌ Ошибка получения файлов от TG: {e}")
            await bot.send_message(chat_id, "⚠️ Telegram не успел отдать файлы. Попробуйте еще раз.")
            return

        # Важно: берем токен из объекта бота, который точно инициализирован
        current_token = bot.token
        char_url = f"https://api.telegram.org/file/bot{current_token}/{photo_file.file_path}"
        motion_url = f"https://api.telegram.org/file/bot{current_token}/{video_file.file_path}"

        # 2. Запрос к API Kling (ожидаем завершения генерации)
        # Внутри process_motion_control должен быть цикл ожидания статуса 'completed'
        result_bytes, _, _ = await process_motion_control(
            prompt, char_url, motion_url, mode=mode, character_orientation=character_orientation
        )

        if not result_bytes:
            logging.error(f"❌ API не вернуло байты видео для {user_id}")
            await bot.send_message(chat_id, "❌ Не удалось получить видео от нейросети.")
            return

        # 3. Сжатие, если файл больше 7МБ (для стабильной отправки)
        if len(result_bytes) > 7 * 1024 * 1024:
            logging.info(f"📹 Видео слишком тяжелое ({len(result_bytes) // 1024} KB), сжимаем...")
            result_bytes = await compress_video(result_bytes, user_id)

        # 4. Отправка пользователю
        logging.info(f"📤 Отправка готового видео пользователю {user_id}...")
        file_id = await save_video_to_telegram(bot, result_bytes, user_id)

        if file_id:
            # Списываем баланс только при успешной отправке
            await charge(user_id, cost_model)
            logging.info(f"✅ Успешно завершено для {user_id}")
        else:
            # Если save_video_to_telegram вернул None, значит была ошибка в BufferedInputFile
            await bot.send_message(chat_id, "❌ Ошибка при формировании видео-файла.")

    except Exception as e:
        logging.error(f"❌ Критическая ошибка Motion: {e}")
        logging.error(traceback.format_exc())
        await bot.send_message(chat_id, "⚠️ Произошла внутренняя ошибка при обработке видео.")