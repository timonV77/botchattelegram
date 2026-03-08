import logging
import traceback
import asyncio
from typing import Tuple, Optional, Any, List
from app.network import process_with_polza, process_video_polza
import database as db

COSTS = {
    "nanabanana": 1,
    "nanabanana_pro": 5,
    "seedream": 2,
    "kling_5": 5,
    "kling_10": 10,
    "kling_motion": 5
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

# ================================
# 🔥 ГЕНЕРАЦИЯ ФОТО
# ================================
async def generate(image_urls: List[str], prompt: str, model: str) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    """Генерация изображений. Возвращает (байты, расширение, прямая_ссылка)."""
    try:
        logging.info(f"--- 🛠 Запуск генерации фото: {model} ---")

        result = await process_with_polza(prompt, model, image_urls)

        # Проверка: если результат пустой или нет ссылки (третий элемент в кортеже)
        if not result or len(result) < 3 or result[2] is None:
            logging.warning(f"⚠️ [API] {model} вернул ошибку, статус FAILED или пустой URL.")
            return None, None, None

        img_bytes, ext, result_url = result

        logging.info(f"✅ [УСПЕХ] {model} готов. URL: {result_url}")
        return img_bytes, ext, result_url

    except Exception as e:
        logging.error(f"❌ [GENERATE ERROR]: {e}")
        return None, None, None

# ================================
# 🔥 ГЕНЕРАЦИЯ ВИДЕО
# ================================
async def generate_video(image_url: str, prompt: str, model: str = "kling_5") -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    """Генерация видео. Возвращает (байты, расширение, прямая_ссылка)."""
    try:
        logging.info(f"--- 🎬 Запуск видео: {model} ---")

        result = await process_video_polza(prompt, model, image_url)

        # Проверка: если результат пустой или нет ссылки
        if not result or len(result) < 3 or result[2] is None:
            logging.warning(f"⚠️ [API] Видео модель {model} не смогла создать файл (FAILED).")
            return None, None, None

        video_bytes, ext, video_url = result

        logging.info(f"✅ [УСПЕХ] Видео {model} получено. URL: {video_url}")
        return video_bytes, ext, video_url

    except asyncio.TimeoutError:
        logging.error(f"⌛ [TIMEOUT] Глобальный таймаут генерации видео.")
        return None, "timeout", None
    except Exception as e:
        logging.error(f"❌ [VIDEO ERROR]: {traceback.format_exc()}")
        return None, None, None