import os
import aiohttp
import asyncio
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "google/gemini-3-pro-image-preview",
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
        print("❌ POLZA_API_KEY не задан")
        return None, None

    model_id = MODELS_MAP.get(model_type)
    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    # 1. Отправляем запрос на генерацию
    payload = {
        "model": model_id,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024"
    }
    if image_url:
        payload["image_url"] = image_url

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as resp:
                if resp.status not in [200, 201, 202]:
                    err = await resp.text()
                    print(f"❌ Ошибка создания задачи: {resp.status} | {err}")
                    return None, None

                data = await resp.json()
                request_id = data.get("requestId")

                if not request_id:
                    print(f"❌ Не получили requestId. Ответ: {data}")
                    return None, None

            # 2. Цикл проверки статуса (Polling)
            print(f"⏳ Задача {request_id} создана, ждем результат...")

            # Проверяем каждые 3 секунды, максимум 2 минуты (40 итераций)
            for i in range(40):
                await asyncio.sleep(3)

                # Эндпоинт получения результата по requestId
                async with session.get(f"{BASE_URL}/get_result", headers=headers,
                                       params={"requestId": request_id}) as s_resp:
                    if s_resp.status != 200:
                        continue

                    result = await s_resp.json()

                    # Проверяем, есть ли ссылка в ответе
                    # Формат может быть result['url'] или result['data'][0]['url']
                    res_url = result.get("url") or result.get("image_url")
                    if not res_url and "data" in result:
                        res_url = result["data"][0].get("url")

                    if res_url:
                        print(f"✅ Картинка готова на итерации {i + 1}!")
                        return await _download_image_bytes(res_url)

                    # Если есть поле статуса и оно 'failed'
                    if result.get("status") == "error" or result.get("status") == "failed":
                        print(f"❌ Polza AI сообщила об ошибке: {result}")
                        return None, None

            print("❌ Превышено время ожидания (timeout)")

    except Exception as e:
        print(f"❌ Исключение в network.py: {e}")

    return None, None