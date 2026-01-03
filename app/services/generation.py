import logging
import traceback
import asyncio
from app.network import process_with_polza, process_video_polza
import database as db

# Словарь стоимости моделей
COSTS = {
    "nanabanana": 1,
    "nanabanana_pro": 5,
    "seadream": 2,
    "kling_5": 5,
    "kling_10": 10
}

def cost_for(model: str) -> int:
    """Возвращает стоимость для модели. Если модель не найдена, цена 1."""
    return COSTS.get(model, 1)

async def has_balance(user_id: int, model_or_cost) -> bool:
    """
    Проверяет баланс.
    model_or_cost может быть строкой (название модели) или числом.
    """
    try:
        # Определяем стоимость
        if isinstance(model_or_cost, str):
            cost = cost_for(model_or_cost)
        else:
            cost = int(model_or_cost)

        balance = await db.get_balance(user_id)
        return balance >= cost
    except Exception as e:
        logging.error(f"❌ Ошибка has_balance (User {user_id}): {e}")
        return False

async def charge(user_id: int, model_or_cost):
    """Списывает баланс. Принимает название модели или число."""
    try:
        if isinstance(model_or_cost, str):
            cost = cost_for(model_or_cost)
        else:
            cost = int(model_or_cost)

        await db.update_balance(user_id, -cost)
        logging.info(f"✅ [ОПЛАТА] Списано {cost} ⚡ у {user_id}")
    except Exception as e:
        logging.error(f"⚠️ Ошибка списания (User {user_id}): {e}")

async def generate(image_url: str, prompt: str, model: str):
    """Генерация изображений."""
    try:
        logging.info(f"--- 🛠 Запуск генерации: {model} ---")
        img_bytes, ext = await process_with_polza(prompt, model, image_url)

        if not img_bytes:
            logging.warning(f"⚠️ [API] Пустой результат для {model}")
            return None, None

        return img_bytes, ext
    except Exception as e:
        logging.error(f"❌ [GENERATE ERROR]: {traceback.format_exc()}")
        return None, None

async def generate_video(image_url: str, prompt: str, model: str = "kling_5"):
    """Генерация видео."""
    try:
        logging.info(f"--- 🎬 Запуск видео: {model} ---")
        video_bytes, ext = await process_video_polza(prompt, model, image_url)

        if not video_bytes:
            logging.warning(f"⚠️ [API] Пустой результат видео {model}")
            return None, None

        return video_bytes, ext
    except Exception as e:
        logging.error(f"❌ [VIDEO ERROR]: {traceback.format_exc()}")
        return None, None