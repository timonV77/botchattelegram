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
    "nanabanana": "nano-banana",
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
    """Генерация ИЗОБРАЖЕНИЯ с расширенными настройками для Gemini Pro."""
    if not POLZA_API_KEY:
        return None, None

    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    # Базовый payload
    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "aspect_ratio": "1:1"
    }

    # СПЕЦИАЛЬНЫЕ НАСТРОЙКИ ДЛЯ GEMINI PRO (отключение фильтров)
    if "gemini" in model_id.lower():
        payload["safetySettings"] = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]

    if image_urls:
        # Для Gemini Pro всегда используем imageUrls и пробуем передать
        # только первую ссылку, если модель капризничает, но пока шлем список
        if "gemini" in model_id.lower():
            payload["imageUrls"] = image_urls
        else:
            payload["filesUrl"] = image_urls

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        try:
            logging.info(f"📤 Отправка в Polza: {model_id}. Фото: {len(image_urls) if image_urls else 0}")
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as response:
                data = await response.json()

                if response.status not in (200, 201):
                    logging.error(f"❌ Ошибка API Polza ({response.status}): {data}")
                    return None, None

                request_id = data.get("requestId")
                if not request_id:
                    logging.error(f"❌ No requestId: {data}")
                    return None, None

                logging.info(f"✅ Задача принята: {request_id}")

            # Polling
            for _ in range(60):
                await asyncio.sleep(7)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as resp:
                    if resp.status != 200:
                        continue

                    result = await resp.json()
                    status = result.get("status", "").lower()

                    if status == "success" or result.get("url") or result.get("images"):
                        # Проверяем разные варианты ключа с результатом
                        url = result.get("url")
                        if not url and result.get("images"):
                            url = result.get("images")[0]

                        logging.info(f"✨ Успех! Ссылка получена.")
                        return await _download_content_bytes(url)

                    if status in ("failed", "error"):
                        # Если упало, выводим причину, если она есть в ответе
                        reason = result.get("failureReason") or result.get("message") or "Unknown error"
                        logging.error(f"❌ Модель отклонила запрос: {reason}")
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