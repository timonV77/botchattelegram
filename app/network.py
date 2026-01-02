import os
import aiohttp
import asyncio
from dotenv import load_dotenv

load_dotenv()

# 🔑 API-ключ Polza
POLZA_API_KEY = os.getenv("POLZA_API_KEY")

# 🌐 Базовый URL Polza API
BASE_URL = "https://api.polza.ai/api/v1"

# 🧠 Соответствие внутренних имён моделей и моделей Polza
MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seadream": "seedream-v4.5"
}


async def _download_content_bytes(url: str):
    """
    Скачивание результата генерации (изображение или видео)
    с повторными попытками
    """
    timeout = aiohttp.ClientTimeout(total=600)  # до 10 минут
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(5):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "").lower()

                        # Определяем расширение файла
                        ext = "png"
                        if "jpeg" in content_type:
                            ext = "jpg"
                        elif "video" in content_type:
                            ext = "mp4"

                        return await response.read(), ext

                    elif response.status == 404:
                        # Результат ещё не готов
                        await asyncio.sleep(8)

            except Exception as e:
                print(f"⚠️ Ошибка скачивания (попытка {attempt + 1}): {e}")
                await asyncio.sleep(5)

    return None, None


async def process_with_polza(prompt: str, model_type: str, image_url: str = None):
    """
    Генерация ИЗОБРАЖЕНИЯ через Polza AI
    Возвращает: (bytes, расширение) или (None, None)
    """
    if not POLZA_API_KEY:
        print("❌ POLZA_API_KEY не найден")
        return None, None

    model_id = MODELS_MAP.get(model_type)
    if not model_id:
        print(f"❌ Неизвестная модель: {model_type}")
        return None, None

    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_id,
        "prompt": prompt.strip()
    }

    if image_url:
        payload["filesUrl"] = [image_url]
        payload["strength"] = 0.7

    if model_type == "nanabanana_pro":
        payload["resolution"] = "1K"

    session_timeout = aiohttp.ClientTimeout(total=900)  # до 15 минут

    try:
        async with aiohttp.ClientSession(timeout=session_timeout) as session:
            async with session.post(
                f"{BASE_URL}/images/generations",
                headers=headers,
                json=payload
            ) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id:
                    print(f"❌ Не получен requestId: {data}")
                    return None, None

            for _ in range(150):
                await asyncio.sleep(6)
                async with session.get(
                    f"{BASE_URL}/images/{request_id}",
                    headers=headers
                ) as status_response:
                    if status_response.status != 200:
                        continue
                    result = await status_response.json()
                    result_url = (
                        result.get("url")
                        or (result.get("images")[0] if result.get("images") else None)
                    )
                    if result_url:
                        return await _download_content_bytes(result_url)
                    if result.get("status") in ("error", "failed"):
                        print(f"❌ Генерация завершилась с ошибкой: {result}")
                        break

    except Exception as e:
        print(f"❌ Ошибка сети Polza (изображение): {e}")

    return None, None


async def process_video_polza(prompt: str, model_type: str, image_url: str = None):
    """
    Генерация ВИДЕО через Polza AI
    Возвращает: (bytes, расширение) или (None, None)
    """
    if not POLZA_API_KEY:
        print("❌ POLZA_API_KEY не найден")
        return None, None

    model_id = MODELS_MAP.get(model_type)
    if not model_id:
        print(f"❌ Неизвестная модель: {model_type}")
        return None, None

    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_id,
        "prompt": prompt.strip()
    }

    if image_url:
        payload["filesUrl"] = [image_url]
        payload["strength"] = 0.7

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=900)) as session:
            async with session.post(
                f"{BASE_URL}/videos/generations",
                headers=headers,
                json=payload
            ) as response:
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id:
                    print(f"❌ Не получен requestId: {data}")
                    return None, None

            for _ in range(150):
                await asyncio.sleep(6)
                async with session.get(
                    f"{BASE_URL}/videos/{request_id}",
                    headers=headers
                ) as status_response:
                    if status_response.status != 200:
                        continue
                    result = await status_response.json()
                    result_url = result.get("url")
                    if result_url:
                        return await _download_content_bytes(result_url)
                    if result.get("status") in ("error", "failed"):
                        print(f"❌ Генерация видео завершилась с ошибкой: {result}")
                        break

    except Exception as e:
        print(f"❌ Ошибка сети Polza (видео): {e}")

    return None, None
