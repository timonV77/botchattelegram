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
    """Универсальная функция скачивания байтов (фото/видео)"""
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(url, timeout=300) as r:
                if r.status == 200:
                    content_type = r.headers.get("Content-Type", "").lower()
                    if "video" in content_type:
                        ext = "mp4"
                    elif "jpeg" in content_type:
                        ext = "jpg"
                    else:
                        ext = "png"
                    return await r.read(), ext
        except Exception as e:
            print(f"❌ Ошибка при скачивании контента: {e}")
    return None, None


async def process_with_polza(prompt: str, model_type: str, image_url: str = None):
    """Генерация фото (Image-to-Image)"""
    if not POLZA_API_KEY:
        return None, None

    model_id = MODELS_MAP.get(model_type)
    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": model_id,
        "prompt": f"{prompt} (High quality photo, photorealistic)",
    }

    if image_url:
        payload["filesUrl"] = [image_url]
        payload["strength"] = 0.7

    # Дополнительные настройки для Pro модели
    if model_type == "nanabanana_pro":
        payload.update({"resolution": "1K"})

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as resp:
                data = await resp.json()
                request_id = data.get("requestId")
                if not request_id:
                    print(f"❌ Ошибка API фото (запрос): {data}")
                    return None, None

            for i in range(60):
                await asyncio.sleep(4)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as s_resp:
                    if s_resp.status != 200: continue
                    result = await s_resp.json()

                    # Ищем ссылку во всех возможных полях
                    res_url = result.get("url") or (result.get("images")[0] if result.get("images") else None)

                    if res_url:
                        return await _download_content_bytes(res_url)

                    if result.get("status") in ["error", "failed"]:
                        print(f"❌ Ошибка генерации фото: {result}")
                        break
    except Exception as e:
        print(f"❌ Ошибка в network (фото): {e}")
    return None, None


# --- ОБНОВЛЕННАЯ ФУНКЦИЯ ДЛЯ ВИДЕО (KLING 2.5) ---

async def process_video_polza(prompt: str, image_url: str, duration: int):
    """Генерация видео с исправленным поиском ссылки при COMPLETED"""
    if not POLZA_API_KEY:
        return None, None

    headers = {"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "kling2.5-image-to-video",
        "prompt": prompt,
        "duration": duration,
        "imageUrls": [image_url],
        "cfgScale": 0.5
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}/videos/generations", headers=headers, json=payload) as resp:
                data = await resp.json()
                request_id = data.get("requestId")
                if not request_id:
                    print(f"❌ Видео API ошибка (старт): {data}")
                    return None, None

            print(f"⏳ Видео {request_id} создано. Начинаю опрос статуса...")

            for i in range(300):
                await asyncio.sleep(5)
                async with session.get(f"{BASE_URL}/videos/{request_id}", headers=headers) as s_resp:
                    if s_resp.status != 200:
                        continue

                    result = await s_resp.json()
                    status = result.get("status")

                    if i % 6 == 0:
                        print(f"LOG: Видео {request_id} статус -> {status}")

                    # --- УЛУЧШЕННЫЙ ПОИСК ССЫЛКИ ---
                    # Проверяем все возможные ключи
                    video_url = (
                            result.get("videoUrl") or
                            result.get("url") or
                            (result.get("result") if isinstance(result.get("result"), str) else None)
                    )

                    # Если ссылка не найдена в основных полях, проверяем списки
                    if not video_url:
                        res_data = result.get("images") or result.get("videos") or result.get("result")
                        if isinstance(res_data, list) and len(res_data) > 0:
                            video_url = res_data[0]

                    # Если статус завершен успешно
                    if status in ["COMPLETED", "success"]:
                        if video_url:
                            print(f"✅ Ссылка найдена: {video_url}. Скачиваю...")
                            return await _download_content_bytes(video_url)
                        else:
                            # Статус готов, но ссылка еще "долетает" до API
                            print(f"⚠️ Статус {status}, но URL еще не появился. Ждем...")
                            continue

                    if status in ["error", "failed"]:
                        print(f"❌ Ошибка Kling: {result}")
                        break

            print(f"⚠️ Видео {request_id} завершилось по таймауту.")

    except Exception as e:
        print(f"❌ Ошибка в network (видео): {e}")

    return None, None