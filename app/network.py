import os
import aiohttp
import asyncio
import logging
from typing import Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seedream": "seedream-v4.5",
    "kling_5": "kling2.5-image-to-video",
    "kling_10": "kling2.5-image-to-video"
}

timeout = aiohttp.ClientTimeout(total=600)


async def _download_content_bytes(url: str) -> Tuple[Optional[bytes], Optional[str]]:
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logging.error(f"❌ Ошибка скачивания: {response.status}")
                    return None, None

                data = await response.read()
                content_type = response.headers.get("Content-Type", "").lower()
                ext = "mp4" if "video" in content_type else "jpg"

                return data, ext

        except Exception as e:
            logging.error(f"❌ Ошибка загрузки файла: {e}")
            return None, None


# ================= IMAGE =================

async def process_with_polza(prompt: str, model_type: str, image_urls: List[str] = None):

    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY не установлен")
        return None, None

    model_id = MODELS_MAP.get(model_type)

    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "aspect_ratio": "1:1",
        "resolution": "1K"
    }

    if image_urls:
        payload["filesUrl"] = image_urls

    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            logging.info(f"📤 Polza запрос. Модель: {model_id}")

            async with session.post(
                    f"{BASE_URL}/images/generations",
                    headers=headers,
                    json=payload
            ) as response:

                text = await response.text()

                if response.status not in (200, 201):
                    logging.error(f"❌ API ошибка {response.status}: {text}")
                    return None, None

                data = await response.json()
                request_id = data.get("requestId")

                if not request_id:
                    logging.error(f"❌ Нет requestId: {data}")
                    return None, None

            # Polling
            for _ in range(60):
                await asyncio.sleep(7)

                async with session.get(
                        f"{BASE_URL}/images/{request_id}",
                        headers=headers
                ) as resp:

                    if resp.status != 200:
                        continue

                    result = await resp.json()
                    status = result.get("status", "").lower()

                    if status == "success":
                        url = result.get("url") or (
                            result.get("images")[0] if result.get("images") else None
                        )

                        if url:
                            logging.info("✅ Polza вернула URL")
                            return await _download_content_bytes(url)

                    if status in ("failed", "error"):
                        logging.error(f"❌ Генерация провалена: {result}")
                        break

        except Exception as e:
            logging.error(f"❌ Сетевая ошибка Polza: {e}")

    return None, None


# ================= VIDEO =================

async def process_video_polza(prompt: str, model_type: str, image_url: str = None):

    if not POLZA_API_KEY:
        return None, None

    model_id = MODELS_MAP.get(model_type)
    duration = 10 if model_type == "kling_10" else 5

    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "duration": duration,
        "cfgScale": 0.5
    }

    if image_url:
        payload["imageUrls"] = [image_url]

    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(
                    f"{BASE_URL}/videos/generations",
                    headers=headers,
                    json=payload
            ) as response:

                data = await response.json()
                request_id = data.get("requestId")

                if not request_id:
                    logging.error("❌ Нет requestId для видео")
                    return None, None

            for _ in range(180):
                await asyncio.sleep(10)

                async with session.get(
                        f"{BASE_URL}/videos/{request_id}",
                        headers=headers
                ) as resp:

                    if resp.status != 200:
                        continue

                    result = await resp.json()
                    status = result.get("status", "").lower()

                    if status == "success":
                        url = result.get("url") or result.get("videoUrl")
                        if url:
                            return await _download_content_bytes(url)

                    if status in ("failed", "error"):
                        logging.error(f"❌ Видео провалено: {result}")
                        break

        except Exception as e:
            logging.error(f"❌ Ошибка генерации видео: {e}")

    return None, None
