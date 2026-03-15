import logging
import traceback
from typing import Tuple, Optional, List

from app.services.models.images.nanabanana import NanoBanana
from app.services.models.images.nanabanana_pro import NanoBananaPro
from app.services.models.images.seedream import Seedream
from app.services.models.video.kling_standard import KlingStandard
from app.services.models.video.kling_motion import KlingMotionControl

import database as db

COSTS = {
    "nanabanana": 1,
    "nanabanana_pro": 5,
    "seedream": 2,
    "kling_5": 5,
    "kling_10": 10,
    "kling_motion": 15
}


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
async def generate(
    image_urls: List[str],
    prompt: str,
    model: str
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    try:
        logging.info("--- 🛠 Выбор модели фото: %s ---", model)

        if model == "nanabanana":
            engine = NanoBanana()
            return await engine.generate(prompt, image_urls=image_urls)

        elif model == "nanabanana_pro":
            engine = NanoBananaPro()
            # ✅ КРИТИЧЕСКИЙ ФИКС: передаём референсы в PRO
            return await engine.generate(prompt, image_urls=image_urls)

        elif model == "seedream":
            engine = Seedream()
            return await engine.generate(prompt, image_urls=image_urls)

        return None, None, None

    except Exception as e:
        logging.error("❌ [GENERATE ERROR]: %s", e)
        logging.error("❌ [GENERATE TRACE]: %s", traceback.format_exc())
        return None, None, None


# ================================
# 🔥 ГЕНЕРАЦИЯ ВИДЕО (Диспетчер)
# ================================
# ================================
# 🔥 ГЕНЕРАЦИЯ ВИДЕО (Диспетчер)
# ================================
async def generate_video(
    image_url: str,
    prompt: str,
    model: str = "kling_5",
    motion_video_url: str = None
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    try:
        logging.info("--- 🎬 Выбор видео-движка: %s ---", model)

        if model == "kling_motion":
            if not image_url or not motion_video_url:
                logging.error("❌ Для kling_motion нужны и фото, и видео референсы")
                return None, None, None
            engine = KlingMotionControl()
            return await engine.generate(prompt, image_url, motion_video_url)

        elif model in ("kling_5", "kling_10"):
            # ✅ Сразу задаём как строки "5" или "10"
            duration = "5" if model == "kling_5" else "10"
            engine = KlingStandard()
            img_list = [image_url] if image_url else None
            return await engine.generate(prompt, image_urls=img_list, duration=duration)

        return None, None, None

    except Exception:
        logging.error("❌ [VIDEO ERROR]: %s", traceback.format_exc())
        return None, None, None