import os
import aiohttp
import asyncio
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seadream": "seedream-v4.5"
}


async def _download_content_bytes(url: str):
    """Скачивание с запасом по времени и 5 попытками"""
    # Таймаут на само скачивание — 10 минут (для тяжелых видео)
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        for attempt in range(5):
            try:
                async with s.get(url) as r:
                    if r.status == 200:
                        content_type = r.headers.get("Content-Type", "").lower()
                        ext = "mp4" if "video" in content_type else "png"
                        if "jpeg" in content_type: ext = "jpg"
                        return await r.read(), ext
                    elif r.status == 404:
                        await asyncio.sleep(10)  # Ждем дольше, если файл еще не на сервере
            except Exception as e:
                print(f"⚠️ Попытка {attempt + 1} скачивания: {e}")
                await asyncio.sleep(5)
    return None, None


async def process_with_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация фото: Ожидание увеличено до 15 минут"""
    if not POLZA_API_KEY: return None, None

    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    # Таймаут сессии — 15 минут
    session_timeout = aiohttp.ClientTimeout(total=900)

    payload = {
        "model": model_id,
        "prompt": f"{prompt[:1000]} (High quality photo, photorealistic)",
    }
    if image_url:
        payload.update({"filesUrl": [image_url], "strength": 0.7})
    if model_type == "nanabanana_pro":
        payload.update({"resolution": "1K"})

    try:
        async with aiohttp.ClientSession(timeout=session_timeout) as session:
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as resp:
                data = await resp.json()
                request_id = data.get("requestId")
                if not request_id: return None, None

            # Опрашиваем 150 раз по 6 секунд = 15 минут
            for i in range(150):
                await asyncio.sleep(6)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as s_resp:
                    if s_resp.status != 200: continue
                    result = await s_resp.json()
                    res_url = result.get("url") or (result.get("images")[0] if result.get("images") else None)

                    if res_url: return await _download_content_bytes(res_url)
                    if result.get("status") in ["error", "failed"]: break
    except Exception as e:
        print(f"❌ Ошибка в network (фото): {e}")
    return None, None


async def process_video_polza(prompt: str, image_url: str, duration: int):
    """Генерация видео: Ожидание увеличено до 1 часа (для Kling 2.5)"""
    if not POLZA_API_KEY: return None, None

    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "kling2.5-image-to-video",
        "prompt": prompt[:1000],
        "duration": duration,
        "imageUrls": [image_url],
        "cfgScale": 0.5
    }

    # Таймаут сессии — 1 час (3600 секунд)
    video_timeout = aiohttp.ClientTimeout(total=3600)

    try:
        async with aiohttp.ClientSession(timeout=video_timeout) as session:
            async with session.post(f"{BASE_URL}/videos/generations", headers=headers, json=payload) as resp:
                data = await resp.json()
                request_id = data.get("requestId")
                if not request_id: return None, None

            print(f"⏳ Видео {request_id} запущено. Лимит ожидания: 60 мин.")

            # Опрашиваем 360 раз по 10 секунд = 60 минут
            for i in range(360):
                await asyncio.sleep(10)
                async with session.get(f"{BASE_URL}/videos/{request_id}", headers=headers) as s_resp:
                    if s_resp.status != 200: continue
                    result = await s_resp.json()
                    status = result.get("status")

                    video_url = result.get("videoUrl") or result.get("url")
                    if not video_url:
                        res_data = result.get("result") or result.get("videos")
                        if isinstance(res_data, list) and len(res_data) > 0:
                            video_url = res_data[0]
                        elif isinstance(res_data, str):
                            video_url = res_data

                    if status in ["COMPLETED", "success"] and video_url:
                        return await _download_content_bytes(video_url)

                    if status in ["error", "failed"]: break
    except Exception as e:
        print(f"❌ Ошибка в network (видео): {e}")
    return None, None