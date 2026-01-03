import os
import aiohttp
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

# Синхронизируем ID моделей с актуальными для Polza AI
MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview",  # Проверьте в консоли Polza, иногда это 'gemini-pro-vision'
    "seadream": "seedream-v4.5",
    "kling_5": "kling-v1-5",
    "kling_10": "kling-v1-10"
}


async def _download_content_bytes(url: str):
    """Скачивание результата с расширенной логикой определения расширения."""
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(5):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.read()
                        content_type = response.headers.get("Content-Type", "").lower()

                        # Определяем расширение
                        ext = "png"
                        if "video" in content_type or "mp4" in url:
                            ext = "mp4"
                        elif "jpeg" in content_type or "jpg" in url:
                            ext = "jpg"

                        logging.info(f"✅ Файл скачан: {len(data)} байт, тип: {ext}")
                        return data, ext
                    elif response.status == 404:
                        logging.warning(f"⚠️ Файл еще не доступен по ссылке (404), ждем...")
                        await asyncio.sleep(5)
            except Exception as e:
                logging.error(f"⚠️ Ошибка скачивания (попытка {attempt + 1}): {e}")
                await asyncio.sleep(5)
    return None, None


async def process_with_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация ИЗОБРАЖЕНИЯ с исправленным парсингом ответа."""
    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY не найден")
        return None, None

    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {"model": model_id, "prompt": prompt.strip()}
    if image_url:
        payload["filesUrl"] = [image_url]
        payload["strength"] = 0.7

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id:
                    logging.error(f"❌ API Error на старте: {data}")
                    return None, None

            logging.info(f"⏳ Ожидание фото {model_type} (ID: {request_id})...")

            for attempt in range(60):  # 6 минут ожидания
                await asyncio.sleep(7)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as status_resp:
                    if status_resp.status != 200: continue
                    result = await status_resp.json()

                    # ГИБКИЙ ПАРСИНГ (ищем URL везде, где он может быть)
                    result_url = (
                            result.get("url") or
                            (result.get("images")[0] if result.get("images") else None) or
                            (result.get("output", [None])[0] if isinstance(result.get("output"), list) else result.get(
                                "output"))
                    )

                    if result_url and result_url.startswith("http"):
                        return await _download_content_bytes(result_url)

                    status = result.get("status", "").lower()
                    if status in ("error", "failed", "rejected"):
                        logging.error(f"❌ API отказало в генерации: {result}")
                        return None, None

            logging.error(f"⌛ Тайм-аут ожидания фото {request_id}")
    except Exception as e:
        logging.error(f"❌ Сетевая ошибка Polza: {e}")
    return None, None


async def process_video_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация ВИДЕО с циклом опроса (Polling)."""
    if not POLZA_API_KEY: return None, None
    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {"model": model_id, "prompt": prompt.strip()}
    if image_url:
        payload["filesUrl"] = [image_url]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}/videos/generations", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id:
                    logging.error(f"❌ API Video Error: {data}")
                    return None, None

            logging.info(f"⏳ Ожидание видео {model_type} (ID: {request_id})...")

            for attempt in range(120):  # До 20 минут ожидания
                await asyncio.sleep(10)
                async with session.get(f"{BASE_URL}/videos/{request_id}", headers=headers) as status_resp:
                    if status_resp.status != 200:
                        logging.warning(f"⚠️ Статус видео {status_resp.status}")
                        continue

                    result = await status_resp.json()
                    status = result.get("status", "").lower()

                    # Ищем URL видео
                    video_url = result.get("url") or (result.get("videoUrl"))

                    if video_url and video_url.startswith("http"):
                        return await _download_content_bytes(video_url)

                    if status in ("error", "failed"):
                        logging.error(f"❌ Ошибка генерации видео: {result}")
                        break

                    # Логируем прогресс, если API его отдает
                    if attempt % 3 == 0:
                        logging.info(f"🎬 Видео {request_id} еще в работе (попытка {attempt})...")

    except Exception as e:
        logging.error(f"❌ Критическая ошибка видео-модуля: {e}")
    return None, None