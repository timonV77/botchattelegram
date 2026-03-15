import base64
import aiohttp
import logging
from aiogram import Bot
from typing import Optional, Tuple

from app.config import settings
from app.network import get_connector


VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv")


def _is_video(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in VIDEO_EXTENSIONS)


async def get_telegram_photo_url(bot: Bot, file_id: str) -> Optional[str]:
    """
    Для видео возвращает прямую ссылку Telegram.
    Для фото пытается загрузить в Telegraph и вернуть постоянную ссылку.
    На любой ошибке возвращает tg_url как fallback (а не None), если удалось получить file_path.
    """
    tg_url: Optional[str] = None

    try:
        file = await bot.get_file(file_id)
        tg_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{file.file_path}"

        if _is_video(file.file_path):
            return tg_url

        timeout = aiohttp.ClientTimeout(total=40, connect=10, sock_read=20)

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            async with session.get(tg_url) as resp:
                if resp.status != 200:
                    logging.warning("⚠️ Не удалось скачать файл из TG для Telegraph, status=%s", resp.status)
                    return tg_url
                file_data = await resp.read()

            form = aiohttp.FormData()
            form.add_field("file", file_data, filename="image.jpg", content_type="image/jpeg")

            async with session.post("https://telegra.ph/upload", data=form) as up_resp:
                if up_resp.status != 200:
                    logging.warning("⚠️ Telegraph upload status=%s", up_resp.status)
                    return tg_url

                result = await up_resp.json(content_type=None)
                # Telegraph обычно возвращает list[{"src": "..."}]
                if isinstance(result, list) and result and isinstance(result[0], dict):
                    path = result[0].get("src")
                    if path:
                        return f"https://telegra.ph{path}"

                logging.warning("⚠️ Неожиданный ответ Telegraph: type=%s body=%r", type(result).__name__, result)
                return tg_url

    except Exception as e:
        logging.error("❌ Ошибка в get_telegram_photo_url: %s", e)

        # Если tg_url уже известен — не рон��ем пайплайн
        if tg_url:
            return tg_url
        return None


async def download_telegram_file(bot: Bot, file_id: str) -> Tuple[Optional[bytes], str]:
    """
    Скачивает файл из Telegram.
    Поддерживает видео до 500МБ и фото до 50МБ.
    """
    try:
        file = await bot.get_file(file_id)
        tg_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{file.file_path}"

        is_video = _is_video(file.file_path)
        mime = "video/mp4" if is_video else "image/jpeg"

        timeout = aiohttp.ClientTimeout(total=600 if is_video else 120, connect=30)
        max_size = (500 if is_video else 50) * 1024 * 1024

        logging.info("📥 Скачивание %s...", "видео" if is_video else "фото")

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            async with session.get(tg_url) as resp:
                if resp.status != 200:
                    logging.error("❌ TG file download status=%s", resp.status)
                    return None, ""

                data = bytearray()
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    data.extend(chunk)
                    if len(data) > max_size:
                        logging.error("❌ Превышен лимит размера файла: %s bytes", len(data))
                        return None, ""

                return bytes(data), mime

    except Exception as e:
        logging.error("❌ Ошибка скачивания: %s", e)
        return None, ""


def bytes_to_base64_data_uri(data: bytes, mime_type: str) -> str:
    """Конвертирует байты в Data URI."""
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"