import os
import aiohttp
import asyncio
import logging
import ssl
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

# Актуальные ID моделей
MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seedream": "seedream-v4.5",
    "kling_5": "kling-v1-5",
    "kling_10": "kling-v1-10"
}


async def _download_content_bytes(url: str):
    """Скачивание результата (фото или видео) в байты с проверкой расширения."""
    # Отключаем проверку SSL для стабильности на некоторых серверах
    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=300)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for attempt in range(5):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.read()
                        content_type = response.headers.get("Content-Type", "").lower()

                        # Определяем расширение
                        if "video" in content_type or "mp4" in url.lower():
                            ext = "mp4"
                        else:
                            ext = "jpg"

                        logging.info(f"✅ Файл успешно скачан ({len(data)} байт, расширение: {ext})")
                        return data, ext
                    logging.warning(f"⚠️ Попытка скачивания {attempt + 1}: статус {response.status}")
                    await asyncio.sleep(3)
            except Exception as e:
                logging.error(f"⚠️ Ошибка скачивания на попытке {attempt + 1}: {e}")
                await asyncio.sleep(5)
    return None, None


async def process_with_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация ИЗОБРАЖЕНИЯ (NanoBanana / SeaDream)."""
    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY не найден в .env")
        return None, None

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

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        try:
            logging.info(f"📤 Запрос фото [{model_type}]: {payload}")
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")

                if not request_id:
                    logging.error(f"❌ Ошибка API (нет requestId): {data}")
                    return None, None

            # Опрос готовности
            for _ in range(60):  # Ждем до 7 минут
                await asyncio.sleep(7)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = result.get("status", "").lower()

                    if status == "success" or result.get("url"):
                        url = result.get("url") or (result.get("images")[0] if result.get("images") else None)
                        if url and url.startswith("http"):
                            return await _download_content_bytes(url)

                    if status in ("failed", "error"):
                        logging.error(f"❌ Генерация фото провалена: {result}")
                        return None, None
        except Exception as e:
            logging.error(f"❌ Сетевая ошибка (фото): {e}")
    return None, None


async def process_video_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация ВИДЕО (Kling)."""
    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY не найден в .env")
        return None, None

    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {"model": model_id, "prompt": prompt.strip()}
    if image_url:
        payload["filesUrl"] = [image_url]

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        try:
            logging.info(f"📤 Запрос видео [{model_type}]: {payload}")
            async with session.post(f"{BASE_URL}/videos/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")

                if not request_id:
                    logging.error(f"❌ Ошибка API (видео): {data}")
                    return None, None
                logging.info(f"✅ Задача создана. ID: {request_id}. Начинаю ожидание...")

            # Опрос готовности (Polling)
            for attempt in range(120):  # До 20 минут
                await asyncio.sleep(10)
                async with session.get(f"{BASE_URL}/videos/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = result.get("status", "").lower()

                    logging.info(f"⏳ Проверка видео {request_id}: статус {status}")

                    # Проверяем все возможные поля с ссылкой
                    video_url = result.get("url") or result.get("videoUrl")

                    if (status == "success" or video_url) and video_url:
                        if video_url.startswith("http"):
                            return await _download_content_bytes(video_url)

                    if status in ("failed", "error"):
                        logging.error(f"❌ Генерация видео провалена: {result}")
                        break

        except Exception as e:
            logging.error(f"❌ Ошибка при обработке видео: {e}")
    return None, None