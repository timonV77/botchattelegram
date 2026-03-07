import os
import aiohttp
import asyncio
import logging
from typing import Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://polza.ai/api/v1"

# ТВОЙ МАРШРУТ МОДЕЛЕЙ (БЕЗ ИЗМЕНЕНИЙ)
MODELS_MAP = {
    "nanabanana": "gemini-2.5-flash-image",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seedream": "bytedance/seedream-4.5",
    "kling_5": "kling2.5-image-to-video",
    "kling_10": "kling2.5-image-to-video",
    "kling_motion": "kling/v2.6-motion-control"
}

# Настройка таймаутов
timeout_config = aiohttp.ClientTimeout(total=600, connect=30, sock_read=300)


def get_connector():
    return aiohttp.TCPConnector(ssl=False)


async def _download_content_bytes(session: aiohttp.ClientSession, url: str) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    try:
        # Извлекаем строку из возможного словаря
        target_url = url.get("url") if isinstance(url, dict) else url
        if not target_url or not isinstance(target_url, str):
            logging.error(f"❌ Некорректный URL для скачивания: {url}")
            return None, None, str(url)

        logging.info(f"📥 Начинаю скачивание готового файла: {target_url[:60]}...")
        async with session.get(target_url) as response:
            if response.status != 200:
                logging.error(f"❌ Ошибка скачивания (HTTP {response.status})")
                return None, None, target_url

            data = await response.read()
            content_type = response.headers.get("Content-Type", "").lower()
            ext = "mp4" if "video" in content_type else "jpg"
            logging.info(f"✅ Файл успешно скачан. Размер: {len(data)} байт")
            return data, ext, target_url
    except Exception as e:
        logging.error(f"❌ Критическая ошибка при скачивании файла: {e}")
        return None, None, str(url)


async def upload_to_telegraph(image_bytes: bytes) -> Optional[str]:
    """
    Загружает изображение на Telegraph и возвращает прямую ссылку.
    """
    try:
        form = aiohttp.FormData()
        form.add_field('file', image_bytes, filename='file.jpg', content_type='image/jpeg')

        async with aiohttp.ClientSession() as session:
            # Официальный эндпоинт загрузки Telegraph
            async with session.post('https://telegra.ph/upload', data=form) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        path = data[0].get('src')
                        full_url = f"https://telegra.ph{path}"
                        logging.info(f"✅ Фото успешно перезалито на Telegraph: {full_url}")
                        return full_url

                logging.error(f"❌ Ошибка загрузки на Telegraph: {resp.status}")
    except Exception as e:
        logging.error(f"❌ Критическая ошибка Telegraph: {e}")

    return None
# ================= IMAGE GENERATION =================

async def process_with_polza(prompt: str, model_type: str, image_urls: List[str] = None) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    logging.info(f"🛠 [START] Модель: {model_type}. Ссылок на фото: {len(image_urls) if image_urls else 0}")

    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY отсутствует")
        return None, None, None

    model_id = MODELS_MAP.get(model_type, "gemini-2.5-flash-image")
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    # Параметр 'quality' обязателен для Seedream 4.5
    input_data = {
        "prompt": prompt.strip(),
        "aspect_ratio": "1:1",
        "quality": "basic"
    }

    if image_urls:
        input_data["images"] = [{"type": "url", "data": url} for url in image_urls]

    payload = {"model": model_id, "input": input_data, "async": True}

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            api_url = f"{BASE_URL}/media"
            async with session.post(api_url, headers=headers, json=payload) as response:
                res_text = await response.text()
                if response.status not in (200, 201):
                    logging.error(f"📥 Ошибка API [{response.status}]: {res_text}")
                    return None, None, None

                data = await response.json()
                request_id = data.get("id")

            logging.info(f"🔑 ID задачи: {request_id}. Ожидание завершения...")

            for attempt in range(1, 101):
                await asyncio.sleep(10)
                async with session.get(f"{BASE_URL}/media/{request_id}", headers=headers) as resp:
                    if resp.status != 200:
                        continue

                    result = await resp.json()
                    status = str(result.get("status", "")).lower()
                    logging.info(f"📡 Статус [{status}] (попытка {attempt})")

                    if status in ("completed", "success"):
                        url = None
                        data_output = result.get("data")

                        if isinstance(data_output, list) and data_output:
                            url = data_output[0]
                        elif isinstance(data_output, dict):
                            url = data_output.get("url")

                        if not url:
                            url = result.get("url")

                        if url:
                            return await _download_content_bytes(session, url)

                    if status in ("failed", "cancelled", "error"):
                        error_data = result.get('error', {})
                        error_msg = error_data.get('message', '') if isinstance(error_data, dict) else str(error_data)

                        if "nsfw" in error_msg.lower():
                            logging.error("❌ Генерация отклонена: обнаружен запрещенный контент (NSFW)")
                        else:
                            logging.error(f"❌ Ошибка генерации: {error_msg}")
                        break
        except Exception as e:
            logging.error(f"❌ Ошибка: {e}", exc_info=True)

    return None, None, None


# ================= VIDEO GENERATION =================

async def process_video_polza(prompt: str, model_type: str, image_url: str = None) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY отсутствует")
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
                res_text = await response.text()
                if response.status not in (200, 201):
                    logging.error(f"📥 Ошибка API видео [{response.status}]: {res_text}")
                    return None, None, None

                data = await response.json()
                request_id = data.get("id") or data.get("requestId")
                if not request_id:
                    return None, None, None

            logging.info(f"🔑 Видео ID: {request_id}. Ожидание...")

            for attempt in range(1, 151):
                await asyncio.sleep(12)
                async with session.get(f"{BASE_URL}/media/{request_id}", headers=headers) as resp:
                    if resp.status != 200:
                        continue

                    result = await resp.json()
                    status = str(result.get("status", "")).lower()
                    logging.info(f"📡 Видео статус -> [{status}] (попытка {attempt})")

                    if status in ("success", "completed"):
                        # Унифицированный поиск URL для видео
                        url = None
                        data_out = result.get("data") or result.get("output")

                        if isinstance(data_out, list) and data_out:
                            url = data_out[0]
                        elif isinstance(data_out, dict):
                            url = data_out.get("url")

                        if not url:
                            url = result.get("url")

                        if url:
                            return await _download_content_bytes(session, url)

                    if status in ("failed", "error"):
                        logging.error(f"❌ Видео не создано: {result.get('error')}")
                        break
        except Exception as e:
            logging.error(f"❌ Ошибка видео-модуля: {e}")

    return None, None, None


# ================= MOTION CONTROL (Kling v2.6) =================

async def process_motion_control(prompt: str, character_image_url: str, motion_video_url: str) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY отсутствует")
        return None, None, None

    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    # ИСПРАВЛЕНИЕ: Используем структуру для генерации медиа, а не текстового чата
    # Для Kling v2.6 Motion часто требуется плоская структура payload
    payload = {
        "model": "kling/v2.6-motion-control",
        "input": {
            "prompt": prompt.strip() if prompt and prompt != "." else "Professional cinematic movement",
            "image_url": character_image_url,
            "video_url": motion_video_url
        },
        "mode": "720p",
        "character_orientation": "image"
    }

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            logging.info("📤 [MOTION CONTROL] Отправка запроса на генерацию...")

            # Попробуем эндпоинт генерации (обычно /generations или /video/generations)
            # Если Polza требует OpenAI-совместимость, пробуем /v1/video/generations
            async with session.post(f"{BASE_URL}/video/generations", headers=headers, json=payload) as response:
                res_text = await response.text()

                # Если 404 на /video/generations, значит провайдер все же хочет /chat/completions,
                # но с ДРУГИМ провайдером внутри. Но ошибка 500 чаще всего лечится сменой эндпоинта.
                if response.status not in (200, 201, 202):
                    logging.error(f"❌ Motion API Error [{response.status}]: {res_text}")
                    return None, None, None

                result = await response.json()
                task_id = result.get("id")

                if not task_id:
                    # Если ссылка пришла сразу (бывает редко)
                    video_url = result.get("url") or result.get("output", {}).get("url")
                    if video_url:
                        return None, "mp4", video_url
                    logging.error(f"❌ Не удалось получить Task ID или URL: {result}")
                    return None, None, None

                # --- ЦИКЛ ОЖИДАНИЯ (POLLING) ---
                logging.info(f"⏳ Видео в очереди (ID: {task_id}). Ожидаем готовности...")
                for _ in range(60):  # Ждем до 5-10 минут (60 итераций по 10 сек)
                    await asyncio.sleep(10)
                    async with session.get(f"{BASE_URL}/tasks/{task_id}", headers=headers) as status_res:
                        if status_res.status == 200:
                            task_data = await status_res.json()
                            status = task_data.get("status")

                            if status == "completed":
                                final_url = task_data.get("output", {}).get("url") or task_data.get("url")
                                logging.info(f"✅ Видео готово: {final_url}")
                                return None, "mp4", final_url

                            if status == "failed":
                                logging.error(f"❌ Генерация провалена: {task_data}")
                                break

                logging.error("⌛ Превышено время ожидания видео.")

        except Exception as e:
            logging.error(f"❌ Ошибка в process_motion_control: {e}")
            logging.error(traceback.format_exc())

    return None, None, None