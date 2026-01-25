import logging
import traceback
import asyncio
# Импортируем типы для аннотаций
from typing import Tuple, Optional, Any
from app.network import process_with_polza, process_video_polza
import database as db

# Словарь стоимости моделей
COSTS = {
    "nanabanana": 1,
    "nanabanana_pro": 5,
    "seedream": 2,
    "kling_5": 5,
    "kling_10": 10
}


def cost_for(model: str) -> int:
    """Возвращает стоимость для модели. Если модель не найдена, цена 1."""
    return COSTS.get(model, 1)


async def has_balance(user_id: int, model_or_cost) -> bool:
    """Проверяет баланс пользователя."""
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
    """Списывает баланс."""
    try:
        if isinstance(model_or_cost, str):
            cost = cost_for(model_or_cost)
        else:
            cost = int(model_or_cost)

        await db.update_balance(user_id, -cost)
        logging.info(f"✅ [ОПЛАТА] Списано {cost} ⚡ у {user_id}")
    except Exception as e:
        logging.error(f"⚠️ Ошибка списания (User {user_id}): {e}")


async def generate(image_url: str, prompt: str, model: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Генерация изображений с детальным логом."""
    try:
        logging.info(f"--- 🛠 Запуск генерации фото: {model} ---")
        logging.info(f"🔗 URL исходника: {image_url}")

        # Ожидаем результат от сетевого модуля
        result = await process_with_polza(prompt, model, image_url)

        if not result or not result[0]:
            logging.warning(f"⚠️ [API] {model} вернул пустой результат. Проверьте API KEY или лимиты.")
            return None, None

        img_bytes, ext = result
        logging.info(f"✅ [УСПЕХ] {model} сгенерировал файл размером {len(img_bytes)} байт")
        return img_bytes, ext

    except Exception as e:
        logging.error(f"❌ [GENERATE ERROR]: {traceback.format_exc()}")
        return None, None


async def generate_video(image_url: str, prompt: str, model: str = "kling_5") -> Tuple[Optional[bytes], Optional[str]]:
    """Генерация видео с увеличенным временем ожидания."""
    try:
        logging.info(f"--- 🎬 Запуск видео: {model} ---")
        logging.info(f"🔗 URL исходника: {image_url}")

        # Пытаемся получить видео
        # ВНИМАНИЕ: Если внутри process_video_polza нет цикла ожидания (polling),
        # этот запрос отвалится по таймауту на стороне nginx/aiohttp.
        result = await process_video_polza(prompt, model, image_url)

        if not result or not result[0]:
            logging.warning(f"⚠️ [API] Видео модель {model} вернула пустоту. Возможно, задача еще в очереди.")
            return None, None

        video_bytes, ext = result
        logging.info(f"✅ [УСПЕХ] Видео {model} получено: {len(video_bytes)} байт")
        return video_bytes, ext

    except asyncio.TimeoutError:
        logging.error(f"⌛ [TIMEOUT] API не ответило за отведенное время при генерации видео.")
        return None, "timeout"
    except Exception as e:
        logging.error(f"❌ [VIDEO ERROR]: {traceback.format_exc()}")
        return None, None