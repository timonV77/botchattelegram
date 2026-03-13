import os
import base64
import aiohttp
import asyncio
import logging
from aiogram import Bot
from typing import Optional, Tuple


async def get_telegram_photo_url(bot: Bot, file_id: str) -> Optional[str]:
    """
    Для фото: пробует Telegraph, если не выходит — дает прямую ссылку.
    Для видео: сразу дает прямую ссылку.
    """
    token = os.getenv("BOT_TOKEN")
    if not token:
        logging.error("❌ BOT_TOKEN не найден в переменных окружения")
        return None

    try:
        file = await bot.get_file(file_id)
        tg_url = f"https://api.telegram.org/file/bot{token}/{file.file_path}"

        if any(ext in file.file_path.lower() for ext in [".mp4", ".mov", ".avi"]):
            logging.info(f"🎥 Видео обнаружено, используем прямую ссылку: {tg_url}")
            return tg_url

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
        return None


async def download_telegram_file(bot: Bot, file_id: str) -> Tuple[Optional[bytes], str]:
    """
    Скачивает файл из Telegram и возвращает (bytes, mime_type).
    Поддерживает большие видео с длительными таймаутами.
    """
    token = os.getenv("BOT_TOKEN")
    if not token:
        logging.error("❌ BOT_TOKEN не найден в переменных окружения")
        return None, ""

    try:
        file = await bot.get_file(file_id)
        tg_url = f"https://api.telegram.org/file/bot{token}/{file.file_path}"

        is_video = any(ext in file.file_path.lower() for ext in [".mp4", ".mov", ".avi", ".mkv"])
        mime = "video/mp4" if is_video else "image/jpeg"

        # Устанавливаем таймаут в зависимости от типа файла
        if is_video:
            # Для видео — длительный таймаут (10 минут)
            timeout = aiohttp.ClientTimeout(total=600, connect=30, sock_read=120)
            max_size = 500 * 1024 * 1024  # 500 MB для видео
        else:
            # Для фото — обычный таймаут (2 минуты)
            timeout = aiohttp.ClientTimeout(total=120, connect=30, sock_read=60)
            max_size = 50 * 1024 * 1024  # 50 MB для фото

        logging.info(
            f"📥 Начинаю скачивание {'видео' if is_video else 'фото'} ({file.file_size / (1024 * 1024) if file.file_size else '?':.1f} MB)...")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(tg_url) as resp:
                if resp.status != 200:
                    logging.error(f"❌ Не удалось скачать файл: HTTP {resp.status}")
                    return None, ""

                # Проверяем размер файла из заголовка
                content_length = resp.headers.get('Content-Length')
                if content_length:
                    file_size = int(content_length)
                    if file_size > max_size:
                        logging.error(
                            f"❌ Файл слишком большой: {file_size / (1024 * 1024):.1f} MB (макс: {max_size / (1024 * 1024):.1f} MB)")
                        return None, ""

                # Скачиваем файл с контролем размера (постепенно по 1 MB)
                data = b''
                chunk_size = 1024 * 1024  # 1 MB на итерацию
                async for chunk in resp.content.iter_chunked(chunk_size):
                    data += chunk
                    if len(data) > max_size:
                        logging.error(
                            f"❌ Файл превышает лимит размера ({max_size / (1024 * 1024):.1f} MB) во время скачивания")
                        return None, ""

                logging.info(f"✅ Файл скачан из TG: {len(data) / 1024:.1f} KB, {mime}")
                return data, mime

    except asyncio.TimeoutError:
        logging.error(f"⏰ Таймаут при скачивании файла из TG")
        return None, ""
    except aiohttp.ClientError as e:
        logging.error(f"❌ Ошибка сети при скачивании файла: {e}")
        return None, ""
    except Exception as e:
        logging.error(f"❌ Ошибка скачивания файла из TG: {e}")
        logging.error(f"   Type: {type(e).__name__}")
        return None, ""


def bytes_to_base64_data_uri(data: bytes, mime_type: str) -> str:
    """
    Конвертирует байты в data URI (base64).

    Args:
        data: Байты файла
        mime_type: MIME тип (например, "image/jpeg" или "video/mp4")

    Returns:
        Data URI строка (например, "data:image/jpeg;base64,...")
    """
    if not mime_type or '/' not in mime_type:
        mime_type = 'application/octet-stream'

    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


async def get_file_size_from_telegram(bot: Bot, file_id: str) -> Optional[int]:
    """
    Получает размер файла из Telegram без скачивания.

    Returns:
        Размер файла в байтах или None
    """
    try:
        file = await bot.get_file(file_id)
        return file.file_size
    except Exception as e:
        logging.error(f"❌ Ошибка получения размера файла: {e}")
        return None