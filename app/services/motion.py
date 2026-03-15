import logging
import traceback
import asyncio
import os
from io import BytesIO
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

        # Добавляем 'nice', чтобы ffmpeg не забирал весь CPU у процесса бота
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

        # Ждем завершения, но не более 5 минут
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
                os.remove(f_path)


async def save_video_to_telegram(bot, video_bytes: bytes, user_id: int) -> str:
    """Кэширует видео в Telegram."""
    try:
        video_file = BytesIO(video_bytes)
        video_file.name = f"motion_{user_id}.mp4"

        temp_message = await bot.send_video(
            chat_id=user_id,
            video=BufferedInputFile(video_bytes, filename=video_file.name),
            caption="🎬 Motion Control (кэшировано)",
        )
        return temp_message.video.file_id
    except Exception as e:
        logging.error(f"❌ Ошибка кэширования: {e}")
        return None


async def background_motion_gen(bot, chat_id: int, char_photo_id: str, motion_video_id: str,
                                prompt: str, user_id: int, mode: str = "720p",
                                character_orientation: str = "image", cost_model: str = "kling_motion_720p"):
    """Оптимизированная фоновая задача для Kling Motion."""
    try:
        logging.info(f"🎭 [MOTION] Старт задачи для {user_id}")

        # 1. Получаем ссылки на файлы с таймаутом (важно для твоего сервера!)
        try:
            photo_file = await asyncio.wait_for(bot.get_file(char_photo_id), timeout=30)
            video_file = await asyncio.wait_for(bot.get_file(motion_video_id), timeout=30)
        except Exception as e:
            logging.error(f"❌ Ошибка получения файлов от TG: {e}")
            await bot.send_message(chat_id, "⚠️ Telegram не ответил вовремя. Попробуйте еще раз.")
            return

        bot_token = os.getenv("BOT_TOKEN")
        char_url = f"https://api.telegram.org/file/bot{bot_token}/{photo_file.file_path}"
        motion_url = f"https://api.telegram.org/file/bot{bot_token}/{video_file.file_path}"

        # 2. Запрос к API Kling
        result_bytes, _, _ = await process_motion_control(
            prompt, char_url, motion_url, mode=mode, character_orientation=character_orientation
        )

        if not result_bytes:
            await bot.send_message(chat_id, "❌ API не вернуло видео. Попробуйте другой промпт.")
            return

        # 3. Сжатие (теперь оно не вешает CPU намертво)
        if len(result_bytes) > 5 * 1024 * 1024:
            logging.info("📹 Сжатие тяжелого видео...")
            result_bytes = await compress_video(result_bytes, user_id)

        # 4. Отправка и кэширование
        file_id = await save_video_to_telegram(bot, result_bytes, user_id)

        if file_id:
            await bot.send_video(
                chat_id=chat_id,
                video=file_id,
                caption="🎭 Motion Control готов!"
            )
            await charge(user_id, cost_model)
            logging.info(f"✅ Успех для {user_id}")
        else:
            await bot.send_message(chat_id, "❌ Ошибка сохранения видео.")

    except Exception as e:
        logging.error(f"❌ Критическая ошибка Motion: {e}")
        traceback.print_exc()
        await bot.send_message(chat_id, "⚠️ Произошла ошибка при генерации.")