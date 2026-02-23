import os
import aiohttp
import asyncio
import logging
from typing import Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://polza.ai/api/v1"

# Карта моделей (ОСТАВЛЕНА БЕЗ ИЗМЕНЕНИЙ)
MODELS_MAP = {
    "nanabanana": "gemini-2.5-flash-image",
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
    logging.info(f"🛠 [START] Модель: {model_type}. Ссылок на фото: {len(image_urls) if image_urls else 0}")

    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY отсутствует")
        return None, None, None

    # BASE_URL берем без api. (согласно OpenAPI серверу в доках)
    base_url_fixed = "https://polza.ai/api/v1"
    model_id = MODELS_MAP.get(model_type, "nano-banana")

    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    # Формируем input строго по MediaRequestDto
    input_data = {
        "prompt": prompt.strip(),
        "aspect_ratio": "1:1"
    }

    # Если есть фото, добавляем их в массив объектов
    if image_urls:
        input_data["images"] = [
            {"type": "url", "data": url} for url in image_urls
        ]

    payload = {
        "model": model_id,
        "input": input_data,
        "async": True
    }

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            # Эндпоинт из OpenAPI: /v1/media
            api_url = f"{base_url_fixed}/media"
            logging.info(f"📤 POST {api_url}")

            async with session.post(api_url, headers=headers, json=payload) as response:
                res_text = await response.text()
                logging.info(f"📥 Response [{response.status}]: {res_text}")

                if response.status not in (200, 201):
                    return None, None, None

                data = await response.json()
                request_id = data.get("id")  # В схеме MediaStatusPresenter это поле 'id'
                if not request_id:
                    return None, None, None

            logging.info(f"🔑 ID задачи: {request_id}. Ожидание завершения...")

            for attempt in range(1, 101):
                await asyncio.sleep(10)
                # Опрос статуса: GET /v1/media/{id}
                async with session.get(f"{base_url_fixed}/media/{request_id}", headers=headers) as resp:
                    if resp.status != 200:
                        continue

                    result = await resp.json()
                    status = result.get("status")
                    logging.info(f"📡 Статус [{status}] (попытка {attempt})")

                    if status == "completed":
                        # Согласно схеме, результат может быть в data или url
                        # Обычно Polza возвращает массив в поле 'data' или прямую ссылку
                        data_output = result.get("data", {})
                        url = None

                        if isinstance(data_output, list) and data_output:
                            url = data_output[0]
                        elif isinstance(data_output, dict):
                            url = data_output.get("url")
                        else:
                            url = result.get("url")

                        if url:
                            return await _download_content_bytes(session, url)

                    if status in ("failed", "cancelled"):
                        logging.error(f"❌ Ошибка генерации: {result.get('error')}")
                        break

        except Exception as e:
            logging.error(f"❌ Ошибка: {e}", exc_info=True)

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