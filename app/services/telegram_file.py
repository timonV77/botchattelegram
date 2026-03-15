import os
import base64
import aiohttp
import asyncio
import logging
from aiogram import Bot
from typing import Optional, Tuple

# Импортируем наши настройки и коннектор
from app.config import settings
from app.network import get_connector


async def get_telegram_photo_url(bot: Bot, file_id: str) -> Optional[str]:
    """
    Загружает фото на Telegraph для получения постоянной ссылки.
    Для видео возвращает прямую временную ссылку TG.
    """
    try:
        file = await bot.get_file(file_id)
        # Используем токен из нашего конфига
        tg_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{file.file_path}"

        if any(ext in file.file_path.lower() for ext in [".mp4", ".mov", ".avi"]):
            return tg_url

        # Используем наш общий коннектор, но для Telegraph создаем отдельную сессию
        # (так как это сторонний сервис)
        async with aiohttp.ClientSession(connector=get_connector()) as session:
            async with session.get(tg_url) as resp:
                if resp.status != 200:
                    return tg_url
                file_data = await resp.read()

            form = aiohttp.FormData()
            form.add_field('file', file_data, filename='image.jpg', content_type='image/jpeg')

            async with session.post('https://telegra.ph/upload', data=form) as up_resp:
                if up_resp.status == 200:
                    result = await up_resp.json()
                    if isinstance(result, list) and len(result) > 0:
                        path = result[0].get('src')
                        return f"https://telegra.ph{path}"

                return tg_url

    except Exception as e:
        logging.error(f"❌ Ошибка в get_telegram_photo_url: {e}")
        return None


async def download_telegram_file(bot: Bot, file_id: str) -> Tuple[Optional[bytes], str]:
    """
    Скачивает файл из Telegram.
    Поддерживает видео до 500МБ и фото до 50МБ.
    """
    try:
        file = await bot.get_file(file_id)
        tg_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{file.file_path}"

        is_video = any(ext in file.file_path.lower() for ext in [".mp4", ".mov", ".avi", ".mkv"])
        mime = "video/mp4" if is_video else "image/jpeg"

        # Настройки таймаутов
        timeout = aiohttp.ClientTimeout(total=600 if is_video else 120, connect=30)
        max_size = (500 if is_video else 50) * 1024 * 1024

        logging.info(f"📥 Скачивание {'видео' if is_video else 'фото'}...")

        # Важно: используем общую сессию бота, если она доступна,
        # или создаем новую с нашим коннектором
        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            async with session.get(tg_url) as resp:
                if resp.status != 200:
                    return None, ""

                data = bytearray()
                async for chunk in resp.content.iter_chunked(1024 * 1024):  # по 1МБ
                    data.extend(chunk)
                    if len(data) > max_size:
                        logging.error("❌ Превышен лимит размера файла")
                        return None, ""

                return bytes(data), mime

    except Exception as e:
        logging.error(f"❌ Ошибка скачивания: {e}")
        return None, ""


def bytes_to_base64_data_uri(data: bytes, mime_type: str) -> str:
    """Конвертирует байты в формат, понятный для API Polza (Data URI)"""
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"