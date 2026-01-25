import os
import aiohttp
import asyncio
import logging
import ssl
from typing import Tuple, Optional
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

# Актуальные ID моделей согласно документации
MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-1.5-pro",
    "seedream": "sea-dream",
    "kling_5": "kling2.5-image-to-video",
    "kling_10": "kling2.5-image-to-video"
}

# Общий коннектор для обхода ошибок SSL на Windows/Linux
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


async def _download_content_bytes(url: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Скачивание результата (фото или видео) в байты."""
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    timeout = aiohttp.ClientTimeout(total=300)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for attempt in range(5):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.read()
                        content_type = response.headers.get("Content-Type", "").lower()
                        ext = "mp4" if "video" in content_type or "mp4" in url.lower() else "jpg"
                        logging.info(f"✅ Файл скачан ({len(data)} байт, тип: {ext})")
                        return data, ext
                    await asyncio.sleep(3)
            except Exception as e:
                logging.error(f"⚠️ Ошибка скачивания (попытка {attempt + 1}): {e}")
                await asyncio.sleep(5)
    return None, None


async def process_with_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация ИЗОБРАЖЕНИЯ."""
    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY не найден")
        return None, None

    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "aspect_ratio": "1:1"
    }

    # Для фото Polza обычно принимает filesUrl или imageUrls (зависит от модели)
    if image_url:
        payload["filesUrl"] = [image_url]

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        try:
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id:
                    logging.error(f"❌ Ошибка фото: {data}")
                    return None, None

            for _ in range(60):
                await asyncio.sleep(7)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    if result.get("status") == "success" or result.get("url"):
                        url = result.get("url") or (result.get("images")[0] if result.get("images") else None)
                        return await _download_content_bytes(url)
                    if result.get("status") in ("failed", "error"): break
        except Exception as e:
            logging.error(f"❌ Ошибка сетевого запроса (фото): {e}")
    return None, None


async def process_video_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация ВИДЕО Kling 2.5 (5 или 10 сек)."""
    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY не найден")
        return None, None

    model_id = MODELS_MAP.get(model_type, "kling2.5-image-to-video")
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    # Логика длительности: строго 5 или 10
    duration = 10 if model_type == "kling_10" else 5

    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "duration": duration,
        "cfgScale": 0.5
    }

    # Важно: По документации для Kling используем imageUrls
    if image_url:
        payload["imageUrls"] = [image_url]

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        try:
            logging.info(f"📤 Отправка в Polza: {model_id} ({duration}s), URL: {image_url}")
            async with session.post(f"{BASE_URL}/videos/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")

                if not request_id:
                    logging.error(f"❌ Ошибка старта видео: {data}")
                    return None, None
                logging.info(f"✅ Задача принята: {request_id}. Ждем результат...")

            # Polling: 180 попыток по 10 сек = 30 минут (для 10-секундных видео)
            for attempt in range(180):
                await asyncio.sleep(10)
                async with session.get(f"{BASE_URL}/videos/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = result.get("status", "").lower()

                    if status == "success" or result.get("url") or result.get("videoUrl"):
                        video_url = result.get("url") or result.get("videoUrl")
                        return await _download_content_bytes(video_url)

                    if status in ("failed", "error"):
                        logging.error(f"❌ Поток API прерван: {result}")
                        break

                if attempt % 6 == 0:  # Логируем статус раз в минуту
                    logging.info(f"⏳ Видео {request_id} в процессе, статус: {status}")

        except Exception as e:
            logging.error(f"❌ Ошибка process_video_polza: {e}")
    return None, None