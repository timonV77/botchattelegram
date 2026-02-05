import os
import aiohttp
import asyncio
import logging
import ssl
from typing import Tuple, Optional, List # Добавили List
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

MODELS_MAP = {
    "nanabanana": "google/gemini-2.5-flash-image",
    "nanabanana_pro": "google/gemini-3-pro-image-preview",
    "seedream": "seedream-v4.5",
    "kling_5": "kling2.5-image-to-video",
    "kling_10": "kling2.5-image-to-video"
}

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

async def _download_content_bytes(url: str) -> Tuple[Optional[bytes], Optional[str]]:
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
                        return data, ext
                    await asyncio.sleep(3)
            except Exception as e:
                logging.error(f"⚠️ Ошибка скачивания: {e}")
                await asyncio.sleep(5)
    return None, None


async def process_with_polza(prompt: str, model_type: str, image_urls: List[str] = None):
    """Генерация ИЗОБРАЖЕНИЯ с поддержкой нескольких референсов."""
    if not POLZA_API_KEY:
        return None, None

    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "aspect_ratio": "1:1"
    }

    if image_urls:
        # Для моделей Gemini часто требуется именно imageUrls вместо filesUrl
        # Мы будем отправлять оба поля для максимальной совместимости,
        # либо выберем одно на основе типа модели
        if "gemini" in model_id.lower():
            payload["imageUrls"] = image_urls
        else:
            payload["filesUrl"] = image_urls

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        try:
            logging.info(
                f"📤 Отправка запроса в Polza. Модель: {model_id}, Фото: {len(image_urls) if image_urls else 0}")
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as response:
                data = await response.json()

                # Добавим подробный лог ответа при ошибке
                if response.status != 200:
                    logging.error(f"❌ Ошибка API Polza ({response.status}): {data}")
                    return None, None

                request_id = data.get("requestId")
                if not request_id:
                    logging.error(f"❌ requestId не получен: {data}")
                    return None, None

            # Ожидание результата (Polling)
            for _ in range(60):
                await asyncio.sleep(7)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = result.get("status", "").lower()

                    if status == "success" or result.get("url"):
                        url = result.get("url") or (result.get("images")[0] if result.get("images") else None)
                        return await _download_content_bytes(url)

                    if status in ("failed", "error"):
                        logging.error(f"❌ Генерация отклонена Polza: {result}")
                        break
        except Exception as e:
            logging.error(f"❌ Сетевая ошибка: {e}")
    return None, None

async def process_video_polza(prompt: str, model_type: str, image_url: str = None):
    """
    Генерация ВИДЕО.
    Примечание: Kling обычно принимает только ОДНО фото как референс.
    """
    if not POLZA_API_KEY: return None, None

    model_id = MODELS_MAP.get(model_type, "kling2.5-image-to-video")
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}
    duration = 10 if model_type == "kling_10" else 5

    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "duration": duration,
        "cfgScale": 0.5
    }

    if image_url:
        payload["imageUrls"] = [image_url] # Kling требует массив, даже если фото одно

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        try:
            async with session.post(f"{BASE_URL}/videos/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id: return None, None

            for attempt in range(180):
                await asyncio.sleep(10)
                async with session.get(f"{BASE_URL}/videos/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = result.get("status", "").lower()
                    if status == "success" or result.get("url"):
                        return await _download_content_bytes(result.get("url") or result.get("videoUrl"))
                    if status in ("failed", "error"): break
        except Exception as e:
            logging.error(f"❌ Ошибка видео: {e}")
    return None, None