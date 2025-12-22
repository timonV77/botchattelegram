import os
import aiohttp
import base64
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

MODEL_NANABANANA = os.getenv("OPENROUTER_MODEL_NANABANANA", "google/gemini-3-pro-image-preview")
MODEL_SEADREAM = os.getenv("OPENROUTER_MODEL_SEADREAM", "google/gemini-2.5-flash-image")

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def decode_data_url(data_url: str):
    header, b64 = data_url.split(",", 1)
    ext = "png"
    if "image/" in header:
        ext = header.split("image/")[1].split(";")[0].strip() or "png"
    return base64.b64decode(b64), ext


async def _download_image_bytes(url: str):
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=180) as r:
            if r.status != 200:
                return None, None
            content_type = (r.headers.get("Content-Type") or "").lower()
            ext = "png"
            if "jpeg" in content_type or "jpg" in content_type:
                ext = "jpg"
            elif "webp" in content_type:
                ext = "webp"
            elif "png" in content_type:
                ext = "png"
            return await r.read(), ext


async def process_with_ai(image_url: str, prompt: str, model_type: str):
    """
    Returns: (img_bytes, ext) or (None, None)
    """
    if not OPENROUTER_API_KEY:
        print("❌ OPENROUTER_API_KEY не найден в .env")
        return None, None

    if model_type == "nanabanana":
        model_id = MODEL_NANABANANA
    elif model_type == "seadream":
        model_id = MODEL_SEADREAM
    else:
        print(f"❌ Неизвестный model_type: {model_type}")
        return None, None

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # Необязательно, но полезно для OpenRouter
        "HTTP-Referer": "https://t.me/your_bot",   # можешь поменять
        "X-Title": "Neuro Photo Bot",
    }

    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": "1:1"},
        "max_tokens": 128
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, headers=headers, json=payload, timeout=180) as resp:
                # сначала пробуем JSON
                if resp.status != 200:
                    raw = await resp.text()
                    print(f"❌ OpenRouter error: {resp.status} | {raw}")
                    return None, None

                try:
                    data = await resp.json()
                except Exception:
                    raw = await resp.text()
                    print(f"❌ OpenRouter: ответ не JSON | {raw}")
                    return None, None

        choices = data.get("choices") or []
        if not choices:
            print(f"❌ Нет choices: {data}")
            return None, None

        msg = choices[0].get("message") or {}

        # основной формат: images[]
        images = msg.get("images") or []
        if images and isinstance(images, list):
            url = images[0].get("image_url", {}).get("url")
            if url:
                if url.startswith("data:image/"):
                    return decode_data_url(url)
                # если это обычный URL
                img_bytes, ext = await _download_image_bytes(url)
                return img_bytes, ext

        print(f"❌ Нет images в message: {msg}")
        return None, None

    except Exception as e:
        print(f"❌ OpenRouter exception: {e}")
        return None, None
