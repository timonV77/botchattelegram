import os
import aiohttp
import asyncio
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview", # ИСПРАВЛЕНО (убрали google/)
    "seadream": "seedream-v4.5"
}

async def _download_image_bytes(url: str):
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=120) as r:
            if r.status == 200:
                content_type = r.headers.get("Content-Type", "").lower()
                ext = "jpg" if "jpeg" in content_type else "png"
                return await r.read(), ext
    return None, None

async def process_with_polza(prompt: str, model_type: str, image_url: str = None):
    if not POLZA_API_KEY:
        return None, None

    model_id = MODELS_MAP.get(model_type)
    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    # Чтобы модель не "сходила с ума", делаем промпт четким
    payload = {
        "model": model_id,
        "prompt": f"{prompt} (High quality photo edit, photorealistic)",
    }

    if image_url:
        payload["filesUrl"] = [image_url]
        # Если модель всё равно плохо меняет фото, подними strength до 0.8
        payload["strength"] = 0.7

    # ИСПРАВЛЕНО: Теперь настройки размеров применяются ВСЕГДА (убрали лишний отступ)
    if model_type == "nanabanana_pro":
        payload["aspect_ratio"] = "1:1"
        payload["resolution"] = "1K" # Добавили по доке
    elif model_type == "seadream":
        payload["size"] = "1:1"
        payload["imageResolution"] = "1K"
    else:
        payload["size"] = "1:1"

    try:
        async with aiohttp.ClientSession() as session:
            # 1. Запрос на генерацию
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as resp:
                data = await resp.json()
                if resp.status not in [200, 201]:
                    print(f"❌ Ошибка API Polza: {data}")
                    return None, None

                request_id = data.get("requestId")
                if not request_id: return None, None

            # 2. Опрос статуса
            print(f"⏳ Задача {request_id} ({model_type}) запущена...")

            for i in range(60):
                await asyncio.sleep(4)
                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as s_resp:
                    if s_resp.status != 200: continue

                    result = await s_resp.json()

                    # Ищем ссылку
                    res_url = (
                        result.get("url") or
                        (result.get("images")[0] if result.get("images") else None) or
                        (result.get("result", {}).get("url") if isinstance(result.get("result"), dict) else None)
                    )

                    if res_url:
                        print(f"✅ Успешно получена ссылка на итерации {i+1}")
                        return await _download_image_bytes(res_url)

                    if result.get("status") in ["error", "failed"]:
                        print(f"❌ Polza сообщила об ошибке: {result}")
                        break

    except Exception as e:
        print(f"❌ Ошибка в network: {e}")

    return None, None