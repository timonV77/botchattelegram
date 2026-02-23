import os
import aiohttp
import asyncio
import logging
from typing import Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

# Карта моделей (ОСТАВЛЕНА БЕЗ ИЗМЕНЕНИЙ)
MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seedream": "seedream-v4.5",
    "kling_5": "kling2.5-image-to-video",
    "kling_10": "kling2.5-image-to-video"
}

# Настройка таймаутов
timeout_config = aiohttp.ClientTimeout(total=600, connect=30, sock_read=300)


def get_connector():
    return aiohttp.TCPConnector(ssl=False)


async def _download_content_bytes(session: aiohttp.ClientSession, url: str) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    try:
        logging.info(f"📥 Начинаю скачивание готового файла: {url[:60]}...")
        async with session.get(url) as response:
            if response.status != 200:
                logging.error(f"❌ Ошибка скачивания (HTTP {response.status})")
                return None, None, url

            data = await response.read()
            content_type = response.headers.get("Content-Type", "").lower()
            ext = "mp4" if "video" in content_type else "jpg"
            logging.info(f"✅ Файл успешно скачан. Размер: {len(data)} байт")
            return data, ext, url
    except Exception as e:
        logging.error(f"❌ Критическая ошибка при скачивании файла: {e}")
        return None, None, url


# ================= IMAGE GENERATION =================

async def process_with_polza(prompt: str, model_type: str, image_urls: List[str] = None) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    if not POLZA_API_KEY:
        logging.error("❌ Ключ POLZA_API_KEY не найден в .env")
        return None, None, None

    model_id = MODELS_MAP.get(model_type, "nano-banana")
    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    # ИСПРАВЛЕНИЕ: Параметры теперь внутри ключа 'input', как требует документация
    payload = {
        "model": model_id,
        "input": {
            "prompt": prompt.strip(),
            "aspect_ratio": "1:1",
            "resolution": "1K"
        },
        "async": True
    }

    # ИСПРАВЛЕНИЕ: Картинки передаются в 'images' в виде объектов с type и data
    if image_urls:
        payload["input"]["images"] = [
            {"type": "url", "data": url} for url in image_urls
        ]

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            logging.info(f"📤 [API POST] Отправка запроса. Модель: {model_id}")
            # В документации указан эндпоинт /media для работы с изображениями и референсами
            async with session.post(f"{BASE_URL}/media", headers=headers, json=payload) as response:
                res_text = await response.text()
                if response.status not in (200, 201):
                    logging.error(f"❌ Ошибка API Polza ({response.status}): {res_text}")
                    return None, None, None

                data = await response.json()
                # Новое API возвращает id вместо requestId
                request_id = data.get("id") or data.get("requestId")
                if not request_id: return None, None, None

            logging.info(f"🔑 Запрос принят. ID: {request_id}. Ожидаю готовности...")

            for attempt in range(1, 101):
                await asyncio.sleep(10)
                # Проверка статуса также через эндпоинт /media
                async with session.get(f"{BASE_URL}/media/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = str(result.get("status", "")).lower()

                    logging.info(f"📡 Попытка {attempt}: Статус нейросети -> [{status}]")

                    if status in ("success", "completed"):
                        # Извлекаем URL из нового формата ответа (поле output или url)
                        output = result.get("output", [])
                        url = output[0] if isinstance(output, list) and output else result.get("url")

                        if url:
                            logging.info(f"🎯 Фото готово!")
                            return await _download_content_bytes(session, url)

                    if status in ("failed", "error", "canceled"):
                        logging.error(f"❌ ГЕНЕРАЦИЯ ПРОВАЛЕНА: {result}")
                        break
        except Exception as e:
            logging.error(f"❌ Сетевое исключение: {e}")

    return None, None, None


# ================= VIDEO GENERATION =================

async def process_video_polza(prompt: str, model_type: str, image_url: str = None) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    if not POLZA_API_KEY:
        return None, None, None

    model_id = MODELS_MAP.get(model_type, "kling2.5-image-to-video")
    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_id,
        "input": {
            "prompt": prompt.strip(),
            "duration": 10 if model_type == "kling_10" else 5,
            "cfgScale": 0.5
        },
        "async": True
    }
    if image_url:
        payload["input"]["images"] = [{"type": "url", "data": image_url}]

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            logging.info(f"📤 [VIDEO POST] Запуск. Модель: {model_id}")
            async with session.post(f"{BASE_URL}/media", headers=headers, json=payload) as response:
                if response.status not in (200, 201):
                    return None, None, None
                data = await response.json()
                request_id = data.get("id") or data.get("requestId")
                if not request_id: return None, None, None

            for attempt in range(1, 151):
                await asyncio.sleep(12)
                async with session.get(f"{BASE_URL}/media/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = str(result.get("status", "")).lower()

                    logging.info(f"📡 Видео статус -> [{status}] (попытка {attempt})")

                    if status in ("success", "completed"):
                        output = result.get("output", [])
                        url = output[0] if isinstance(output, list) and output else result.get("url")
                        if url:
                            return await _download_content_bytes(session, url)

                    if status in ("failed", "error"):
                        break
        except Exception as e:
            logging.error(f"❌ Ошибка видео-модуля: {e}")

    return None, None, None