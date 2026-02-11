import logging
import traceback
import asyncio
from typing import Tuple, Optional, Any, List # Добавили List
from app.network import process_with_polza, process_video_polza
import database as db

COSTS = {
    "nanabanana": 1,
    "nanabanana_pro": 5,
    "seedream": 2,
    "kling_5": 5,
    "kling_10": 10
}

def cost_for(model: str) -> int:
    return COSTS.get(model, 1)

async def has_balance(user_id: int, model_or_cost) -> bool:
    try:
        if isinstance(model_or_cost, str):
            cost = cost_for(model_or_cost)
        else:
            cost = int(model_or_cost)
        balance = await db.get_balance(user_id)
        logging.info(f"📊 [BALANCE] User {user_id}: {balance}, Cost: {cost}")
        return balance >= cost
    except Exception as e:
        logging.error(f"❌ Ошибка has_balance (User {user_id}): {e}")
        return False

async def charge(user_id: int, model_or_cost):
    try:
        if isinstance(model_or_cost, str):
            cost = cost_for(model_or_cost)
        else:
            cost = int(model_or_cost)
        await db.update_balance(user_id, -cost)
        logging.info(f"✅ [ОПЛАТА] Списано {cost} ⚡ у {user_id}")
    except Exception as e:
        logging.error(f"⚠️ Ошибка списания (User {user_id}): {e}")

# Исправлено: теперь принимает List[str], так как в photo.py мы передаем список ссылок
async def generate(image_urls: List[str], prompt: str, model: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Генерация изображений с поддержкой списка URL."""
    try:
        logging.info(f"--- 🛠 Запуск генерации фото: {model} ---")
        logging.info(f"🔗 URL исходников: {image_urls}")

        # Передаем список в network.py
        result = await process_with_polza(prompt, model, image_urls)

        if not result or not result[0]:
            logging.warning(f"⚠️ [API] {model} вернул пустой результат.")
            return None, None

        img_bytes, ext = result
        logging.info(f"✅ [УСПЕХ] {model} сгенерировал файл размером {len(img_bytes)} байт")
        return img_bytes, ext

    except Exception as e:
        logging.error(f"❌ [GENERATE ERROR]: {traceback.format_exc()}")
        return None, None

async def generate_video(image_url: str, prompt: str, model: str = "kling_5") -> Tuple[Optional[bytes], Optional[str]]:
    try:
        logging.info(f"--- 🎬 Запуск видео: {model} ---")
        result = await process_video_polza(prompt, model, image_url)

        if not result or not result[0]:
            logging.warning(f"⚠️ [API] Видео модель {model} не смогла создать файл.")
            return None, None

        video_bytes, ext = result
        logging.info(f"✅ [УСПЕХ] Видео {model} получено: {len(video_bytes)} байт")
        return video_bytes, ext

    except asyncio.TimeoutError:
        logging.error(f"⌛ [TIMEOUT] Глобальный таймаут генерации видео.")
        return None, "timeout"
    except Exception as e:
        logging.error(f"❌ [VIDEO ERROR]: {traceback.format_exc()}")
        return None, None