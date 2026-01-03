import os
import aiohttp
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

# Актуальные ID моделей
MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seadream": "seedream-v4.5",
    "kling_5": "kling-v1-5",
    "kling_10": "kling-v1-10"
}


async def _download_content_bytes(url: str):
    """Скачивание результата с определением расширения."""
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(5):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.read()
                        content_type = response.headers.get("Content-Type", "").lower()
                        ext = "mp4" if "video" in content_type or "mp4" in url else "jpg"
                        logging.info(f"✅ Файл скачан: {len(data)} байт")
                        return data, ext
                    await asyncio.sleep(5)
            except Exception as e:
                logging.error(f"⚠️ Ошибка скачивания: {e}")
                await asyncio.sleep(5)
    return None, None


async def process_with_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация ИЗОБРАЖЕНИЯ."""
    if not POLZA_API_KEY: return None, None
    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "aspect_ratio": "1:1"
    }
    if image_url:
        payload["filesUrl"] = [image_url]
        if model_type != "nanabanana_pro":
            payload["strength"] = 0.7

    if model_type == "nanabanana_pro":
        payload["resolution"] = "1K"

    async with aiohttp.ClientSession() as session:
        try:
            logging.info(f"📤 Запрос фото {model_type}: {payload}")
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id:
                    logging.error(f"❌ API Error: {data}")
                    return None, None

            for _ in range(60):
                await asyncio.sleep(7)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()

                    url = result.get("url") or (result.get("images")[0] if result.get("images") else None)
                    if url and url.startswith("http"):
                        return await _download_content_bytes(url)

                    if result.get("status", "").lower() in ("failed", "error"):
                        logging.error(f"❌ API отказало (FAILED): {result}")
                        return None, None
        except Exception as e:
            logging.error(f"❌ Сетевая ошибка: {e}")
    return None, None


async def process_video_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация ВИДЕО."""
    if not POLZA_API_KEY: return None, None
    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {"model": model_id, "prompt": prompt.strip()}
    if image_url:
        payload["filesUrl"] = [image_url]

    async with aiohttp.ClientSession() as session:
        try:
            logging.info(f"📤 Запрос видео {model_type}: {payload}")
            async with session.post(f"{BASE_URL}/videos/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id: return None, None

            for _ in range(120):
                await asyncio.sleep(10)
                async with session.get(f"{BASE_URL}/videos/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()

                    video_url = result.get("url") or result.get("videoUrl")
                    if video_url and video_url.startswith("http"):
                        return await _download_content_bytes(video_url)

                    if result.get("status", "").lower() in ("failed", "error"):
                        break
        except Exception as e:
            logging.error(f"❌ Ошибка видео: {e}")
    return None, None