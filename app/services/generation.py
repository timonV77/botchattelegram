import logging
import traceback
import asyncio
from typing import Tuple, Optional, List

# Импорты наших классов
from app.services.models.images.nanabanana import NanoBanana
from app.services.models.images.nanabanana_pro import NanoBananaPro
from app.services.models.images.seedream import Seedream
from app.services.models.video.kling_standard import KlingStandard
from app.services.models.video.kling_motion import KlingMotionControl  # Исправили имя

import database as db

COSTS = {
    "nanabanana": 1,
    "nanabanana_pro": 5,
    "seedream": 2,
    "kling_5": 5,
    "kling_10": 10,
    "kling_motion": 15  # Motion Control обычно дороже
}


# --- Логика баланса остается без изменений ---
async def has_balance(user_id: int, model_or_cost) -> bool:
    try:
        cost = COSTS.get(model_or_cost, model_or_cost) if isinstance(model_or_cost, str) else model_or_cost
        balance = await db.get_balance(user_id)
        return balance >= cost
    except Exception:
        return False


async def charge(user_id: int, model_or_cost):
    cost = COSTS.get(model_or_cost, model_or_cost) if isinstance(model_or_cost, str) else model_or_cost
    await db.update_balance(user_id, -cost)


# ================================
# 🔥 ГЕНЕРАЦИЯ ФОТО (Диспетчер)
# ================================
async def generate(image_urls: List[str], prompt: str, model: str) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    try:
        logging.info(f"--- 🛠 Выбор модели фото: {model} ---")

        if model == "nanabanana":
            engine = NanoBanana()
            # Nano Banana поддерживает референсы
            return await engine.generate(prompt, image_urls=image_urls)

        elif model == "nanabanana_pro":
            engine = NanoBananaPro()
            return await engine.generate(prompt)

        elif model == "seedream":
            engine = Seedream()
            # Seedream поддерживает до 14 референсов
            return await engine.generate(prompt, image_urls=image_urls)

        return None, None, None

    except Exception as e:
        logging.error(f"❌ [GENERATE ERROR]: {e}")
        return None, None, None


# ================================
# 🔥 ГЕНЕРАЦИЯ ВИДЕО (Диспетчер)
# ================================
async def generate_video(image_url: str, prompt: str, model: str = "kling_5", motion_video_url: str = None) -> Tuple[
    Optional[bytes], Optional[str], Optional[str]]:
    try:
        logging.info(f"--- 🎬 Выбор видео-движка: {model} ---")

        if model == "kling_motion":
            if not image_url or not motion_video_url:
                logging.error("❌ Для kling_motion нужны и фото, и видео референсы")
                return None, None, None
            engine = KlingMotionControl()
            return await engine.generate(prompt, image_url, motion_video_url)

        elif model in ("kling_5", "kling_10"):
            # В KlingStandard длительность передается числом
            duration = 5 if model == "kling_5" else 10
            engine = KlingStandard()
            # Передаем image_url как список для совместимости с логикой модели
            img_list = [image_url] if image_url else None
            return await engine.generate(prompt, image_urls=img_list, duration=duration)

        return None, None, None

    except Exception as e:
        logging.error(f"❌ [VIDEO ERROR]: {traceback.format_exc()}")
        return None, None, None