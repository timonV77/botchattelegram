import os
import aiohttp
import logging
from aiogram import Bot
from typing import Optional


async def _upload_video_to_tmpfiles(video_bytes: bytes, filename: str = "video.mp4") -> Optional[str]:
    """
    Заливает видео на tmpfiles.org (до 100MB, живёт 60 минут).
    Возвращает прямую публичную ссылку.
    """
    try:
        form = aiohttp.FormData()
        form.add_field('file', video_bytes, filename=filename, content_type='video/mp4')

        async with aiohttp.ClientSession() as session:
            async with session.post('https://tmpfiles.org/api/v1/upload', data=form) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    url = data.get("data", {}).get("url", "")
                    if url:
                        # tmpfiles.org отдаёт страницу, прямая ссылка через /dl/
                        direct_url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                        logging.info(f"✅ Видео залито на tmpfiles: {direct_url}")
                        return direct_url

                logging.error(f"❌ tmpfiles ошибка: {resp.status}")
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки видео на tmpfiles: {e}")

    return None


async def get_telegram_photo_url(bot: Bot, file_id: str) -> Optional[str]:
    """
    Для фото: пробует Telegraph, если не выходит — дает прямую ссылку.
    Для видео: скачивает из TG и заливает на публичный хостинг.
    """
    token = os.getenv("BOT_TOKEN")
    if not token:
        logging.error("❌ BOT_TOKEN не найден в переменных окружения")
        return None

    try:
        # 1. Получаем объект файла из Telegram
        file = await bot.get_file(file_id)
        tg_url = f"https://api.telegram.org/file/bot{token}/{file.file_path}"

        # 2. Если это видео — скачиваем и заливаем на публичный хостинг
        if any(ext in file.file_path.lower() for ext in [".mp4", ".mov", ".avi"]):
            logging.info(f"🎥 Видео обнаружено, скачиваем из Telegram...")
            async with aiohttp.ClientSession() as session:
                async with session.get(tg_url) as resp:
                    if resp.status != 200:
                        logging.warning(f"⚠️ Не удалось скачать видео из TG: {resp.status}")
                        return tg_url  # fallback
                    video_bytes = await resp.read()
                    logging.info(f"📦 Видео скачано: {len(video_bytes)} байт")

            # Заливаем на публичный хостинг
            public_url = await _upload_video_to_tmpfiles(video_bytes)
            if public_url:
                return public_url

            # Если хостинг не сработал — fallback на прямую ссылку TG
            logging.warning("⚠️ Не удалось залить видео, используем прямую ссылку TG")
            return tg_url

        # 3. Для фото — пытаемся залить на Telegraph
        async with aiohttp.ClientSession() as session:
            async with session.get(tg_url) as resp:
                if resp.status != 200:
                    logging.warning(f"⚠️ Не удалось скачать файл из TG, статус: {resp.status}")
                    return tg_url
                file_data = await resp.read()

            form = aiohttp.FormData()
            form.add_field('file', file_data, filename='image.jpg', content_type='image/jpeg')

            async with session.post('https://telegra.ph/upload', data=form) as up_resp:
                if up_resp.status == 200:
                    result = await up_resp.json()
                    if isinstance(result, list) and len(result) > 0:
                        path = result[0].get('src')
                        res_url = f"https://telegra.ph{path}"
                        logging.info(f"✅ Фото на Telegraph: {res_url}")
                        return res_url

                logging.warning(f"⚠️ Telegraph (код {up_resp.status}), используем прямую ссылку")
                return tg_url

    except Exception as e:
        logging.error(f"❌ Ошибка в get_telegram_photo_url: {e}")
        return f"https://api.telegram.org/file/bot{token}/{file_id}"