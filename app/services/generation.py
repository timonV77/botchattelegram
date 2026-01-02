import logging
import traceback
from app.network import process_with_polza, process_video_polza
import database as db

# Словарь стоимости моделей
COSTS = {
    "nanabanana": 1,
    "nanabanana_pro": 5,
    "seadream": 2,
    "kling_5": 5,  # 5 секунд видео = 5 генераций
    "kling_10": 10  # 10 секунд видео = 10 генераций
}


def cost_for(model: str) -> int:
    """Возвращает стоимость генерации для конкретной модели."""
    return COSTS.get(model, 1)


def has_balance(user_id: int, cost: int) -> bool:
    """Проверяет баланс пользователя с защитой от ошибок базы."""
    try:
        balance = db.get_balance(user_id)
        return balance >= cost
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке баланса (User {user_id}): {e}")
        # В случае ошибки базы лучше вернуть False, чтобы не генерировать бесплатно
        return False


def charge(user_id: int, cost: int):
    """Списывает стоимость с баланса. Если база упадет, бот продолжит работу."""
    try:
        db.update_balance(user_id, -cost)
        print(f"✅ [ОПЛАТА] Списано {cost} ⚡ у пользователя {user_id}")
    except Exception as e:
        print(f"⚠️ [ВНИМАНИЕ] Ошибка списания (User {user_id}): {e}")
        # Мы не кидаем raise, чтобы пользователь получил свое фото, даже если баланс не обновился
        pass


async def generate(image_url: str, prompt: str, model: str):
    """Основная функция для генерации ИЗОБРАЖЕНИЙ с логированием."""
    try:
        print(f"--- 🛠 Запуск генерации: {model} ---")
        img_bytes, ext = await process_with_polza(prompt, model, image_url)

        if not img_bytes:
            print(f"⚠️ [API] Нейросеть вернула пустой результат для {model}")
            return None, None

        return img_bytes, ext

    except Exception as e:
        print(f"❌ [КРИТИЧЕСКАЯ ОШИБКА GENERATE]:\n{traceback.format_exc()}")
        return None, None


async def generate_video(image_url: str, prompt: str, model: str = "kling_5"):
    """Основная функция для генерации ВИДЕО через Polza AI."""
    try:
        print(f"--- 🎬 Запуск видео для модели {model} ---")
        video_bytes, ext = await process_video_polza(prompt, model, image_url)

        if not video_bytes:
            print(f"⚠️ [API] Нейросеть вернула пустой результат для видео {model}")
            return None, None

        return video_bytes, ext

    except Exception as e:
        print(f"❌ [КРИТИЧЕСКАЯ ОШИБКА VIDEO]:\n{traceback.format_exc()}")
        return None, None
