import os
import aiohttp
import asyncio
import logging
from typing import Tuple, Optional, List
from dotenv import load_dotenv
import traceback

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://polza.ai/api/v1"

MODELS_MAP = {
    "nanabanana": "gemini-2.5-flash-image",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seedream": "bytedance/seedream-4.5",
    "kling_5": "kling2.5-image-to-video",
    "kling_10": "kling2.5-image-to-video",
    "kling_motion": "kling/v2.6-motion-control"
}

# Настройка таймаутов: общее время 10 мин, но ожидание данных 5 мин
timeout_config = aiohttp.ClientTimeout(total=600, connect=30, sock_read=300)


def get_connector():
    # Оставляем ssl=False, так как на сервере Novalocal проблемы с сертификатами
    return aiohttp.TCPConnector(ssl=False)


async def _download_content_bytes(session: aiohttp.ClientSession, url: str) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    try:
        target_url = url.get("url") if isinstance(url, dict) else url
        if not target_url or not isinstance(target_url, str):
            logging.error(f"❌ Некорректный URL для скачивания: {url}")
            return None, None, str(url)

        logging.info(f"📥 Начинаю скачивание готового файла: {target_url[:60]}...")
        async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=300)) as response:
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
    """Быстрая загрузка фото на Telegraph."""
    try:
        form = aiohttp.FormData()
        form.add_field('file', image_bytes, filename='file.jpg', content_type='image/jpeg')

        async with aiohttp.ClientSession(connector=get_connector()) as session:
            async with session.post('https://telegra.ph/upload', data=form, timeout=60) as resp:
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


async def upload_file_to_host(file_bytes: bytes, filename: str = None) -> Optional[str]:
    """Загрузка файла на Telegraph (поддерживает фото и видео до 50MB)."""
    file_size_mb = len(file_bytes) / (1024 * 1024)
    try:
        logging.info(f"📤 Загрузка на Telegraph ({file_size_mb:.1f} MB)...")
        form = aiohttp.FormData()

        if filename and filename.endswith('.mp4'):
            content_type = 'video/mp4'
        elif filename and filename.endswith(('.jpg', '.jpeg')):
            content_type = 'image/jpeg'
        else:
            content_type = 'application/octet-stream'

        form.add_field('file', file_bytes, filename=filename or 'file.bin', content_type=content_type)
        timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=120)

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            async with session.post('https://telegra.ph/upload', data=form) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        path = data[0].get('src')
                        full_url = f"https://telegra.ph{path}"
                        logging.info(f"✅ Telegraph успешно: {full_url}")
                        return full_url
                else:
                    error_text = await resp.text()
                    logging.error(f"❌ Telegraph ошибка [{resp.status}]: {error_text[:100]}")
    except Exception as e:
        logging.error(f"❌ Ошибка Telegraph: {e}")
    return None


# ================= IMAGE GENERATION =================

async def process_with_polza(prompt: str, model_type: str, image_urls: List[str] = None) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    if not POLZA_API_KEY:
        logging.error("❌ POLZA_API_KEY отсутствует")
        return None, None, None

    model_id = MODELS_MAP.get(model_type, "gemini-2.5-flash-image")
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    input_data = {
        "prompt": (prompt or "").strip(),
        "aspect_ratio": "1:1",
        "quality": "basic"
    }
    if image_urls:
        input_data["images"] = [{"type": "url", "data": url} for url in image_urls]

    payload = {"model": model_id, "input": input_data, "async": True}

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            async with session.post(f"{BASE_URL}/media", headers=headers, json=payload) as response:
                if response.status not in (200, 201):
                    return None, None, None
                data = await response.json()
                request_id = data.get("id")

            for attempt in range(1, 101):
                await asyncio.sleep(10)
                async with session.get(f"{BASE_URL}/media/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = str(result.get("status", "")).lower()
                    if status in ("completed", "success"):
                        url = result.get("url") or (result.get("data")[0] if result.get("data") else None)
                        if url: return await _download_content_bytes(session, url)
                    if status in ("failed", "cancelled", "error"): break
        except Exception as e:
            logging.error(f"❌ Ошибка: {e}")
    return None, None, None


# ================= VIDEO GENERATION =================

async def process_video_polza(prompt: str, model_type: str, image_url: str = None) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    if not POLZA_API_KEY: return None, None, None
    model_id = MODELS_MAP.get(model_type, "kling2.5-image-to-video")
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": model_id,
        "input": {
            "prompt": (prompt or "").strip(),
            "duration": 10 if model_type == "kling_10" else 5,
            "cfgScale": 0.5
        },
        "async": True
    }
    if image_url: payload["input"]["images"] = [{"type": "url", "data": image_url}]

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            async with session.post(f"{BASE_URL}/media", headers=headers, json=payload) as response:
                if response.status not in (200, 201): return None, None, None
                data = await response.json()
                request_id = data.get("id") or data.get("requestId")

            for attempt in range(1, 151):
                await asyncio.sleep(12)
                async with session.get(f"{BASE_URL}/media/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = str(result.get("status", "")).lower()
                    if status in ("success", "completed"):
                        url = result.get("url") or (result.get("data")[0] if result.get("data") else None)
                        if url: return await _download_content_bytes(session, url)
                    if status in ("failed", "error"): break
        except Exception as e:
            logging.error(f"❌ Ошибка видео: {e}")
    return None, None, None


# ================= MOTION CONTROL (Kling v2.6) =================

async def process_motion_control(prompt: str, character_image_url: str, motion_video_url: str,
                                 mode: str = "720p", character_orientation: str = "image") -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    if not POLZA_API_KEY: return None, None, None

    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": "kling/v2.6-motion-control",
        "input": {
            "images": [character_image_url],
            "videos": [motion_video_url],
            "mode": mode,
            "character_orientation": character_orientation
        },
        "async": True
    }
    if prompt and prompt.strip() not in (".", ""):
        payload["input"]["prompt"] = prompt.strip()[:2500]

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            async with session.post(f"{BASE_URL}/media", headers=headers, json=payload) as response:
                data = await response.json()
                request_id = data.get("id") or data.get("requestId")
                if not request_id: return None, None, None

            for attempt in range(1, 81):
                await asyncio.sleep(12)
                async with session.get(f"{BASE_URL}/media/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = str(result.get("status", "")).lower()
                    logging.info(f"📡 Motion [{status}] ({attempt})")

                    if status in ("success", "completed"):
                        data_out = result.get("data") or result.get("output")
                        url = data_out[0] if isinstance(data_out, list) else result.get("url")
                        if url: return await _download_content_bytes(session, url)
                    if status in ("failed", "error", "cancelled"): break
        except Exception as e:
            logging.error(f"❌ Ошибка Motion API: {e}")
    return None, None, None