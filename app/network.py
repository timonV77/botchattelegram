import os
import aiohttp
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

# Добавили модели видео (Kling), чтобы видео начало создаваться!
MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seadream": "seedream-v4.5",
    "kling_5": "kling-v1-5",  # Добавьте актуальный ID модели из доков Polza
    "kling_10": "kling-v1-10"
}


async def _download_content_bytes(url: str):
    """Скачивание результата генерации с повторными попытками."""
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(5):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "").lower()
                        ext = "png"
                        if "jpeg" in content_type:
                            ext = "jpg"
                        elif "video" in content_type or "mp4" in url:
                            ext = "mp4"

                        data = await response.read()
                        logging.info(f"✅ Файл успешно скачан ({len(data)} байт)")
                        return data, ext
                    elif response.status == 404:
                        await asyncio.sleep(5)
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
    if not model_id:
        logging.error(f"❌ Неизвестная модель в MAP: {model_type}")
        return None, None

    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model_id, "prompt": prompt.strip()}

    if image_url:
        payload["filesUrl"] = [image_url]
        payload["strength"] = 0.7

    if model_type == "nanabanana_pro":
        payload["resolution"] = "1K"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id:
                    logging.error(f"❌ API Error: {data}")
                    return None, None

            logging.info(f"⏳ Ожидание фото (ID: {request_id})...")
            for _ in range(100):  # Ожидание до 10 минут
                await asyncio.sleep(6)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as status_resp:
                    if status_resp.status != 200: continue
                    result = await status_resp.json()

                    # Проверка готовности (у разных моделей Polza ключи могут отличаться)
                    result_url = result.get("url") or (result.get("images")[0] if result.get("images") else None)

                    if result_url:
                        return await _download_content_bytes(result_url)
                    if result.get("status") in ("error", "failed"):
                        logging.error(f"❌ Ошибка API: {result}")
                        break
    except Exception as e:
        logging.error(f"❌ Сетевая ошибка Polza: {e}")
    return None, None


async def process_video_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация ВИДЕО."""
    if not POLZA_API_KEY: return None, None
    model_id = MODELS_MAP.get(model_type)
    if not model_id: return None, None

    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model_id, "prompt": prompt.strip()}
    if image_url: payload["filesUrl"] = [image_url]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}/videos/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id: return None, None

            logging.info(f"⏳ Ожидание видео (ID: {request_id})...")
            for _ in range(200):  # Видео делается дольше
                await asyncio.sleep(10)
                async with session.get(f"{BASE_URL}/videos/{request_id}", headers=headers) as status_resp:
                    if status_resp.status != 200: continue
                    result = await status_resp.json()
                    if result.get("url"):
                        return await _download_content_bytes(result.get("url"))
                    if result.get("status") in ("error", "failed"): break
    except Exception as e:
        logging.error(f"❌ Ошибка видео: {e}")
    return None, None