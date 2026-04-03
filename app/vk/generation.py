import logging
import traceback
from typing import Tuple, Optional, List
import os

from app.vk.models.images.nanabanana import NanoBanana
from app.vk.models.images.nanabanana_pro import NanoBananaPro
from app.vk.models.images.seedream import Seedream
from app.vk.models.video.kling_motion import KlingMotionControl

import vk_database as db

# Цены для VK
COSTS = {
    "nanabanana": 17,
    "nanabanana_2": 28,
    "nanabanana_pro": 55,
    "seedream": 26,
    "kling_motion_720": 70,   # 14р/сек * 5сек = 70р (предполагаем 5сек)
    "kling_motion_1080": 100, # 20р/сек * 5сек = 100р (предполагаем 5сек)
}

# Если пользователь хочет именно "за секунду", нам нужно знать длительность.
# Пока заложим фиксированные суммы для простоты или уточним.
# На основе запроса "14р/сек", если клинг стандартно льет 5сек, то это 70р.

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

async def generate_photo(
    image_urls: List[str],
    prompt: str,
    model: str
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    try:
        logging.info("--- 🛠 VK Фото-генерация: %s ---", model)

        if model == "nanabanana":
            engine = NanoBanana()
            return await engine.generate(prompt, image_urls=image_urls)

        elif model == "nanabanana_2":
            engine = NanoBanana(version="v2")
            return await engine.generate(prompt, image_urls=image_urls)

        elif model == "nanabanana_pro":
            engine = NanoBananaPro()
            return await engine.generate(prompt, image_urls=image_urls)

        elif model == "seedream":
            engine = Seedream()

            return await engine.generate(prompt, image_urls=image_urls)

        return None, None, None
    except Exception as e:
        logging.error(f"❌ VK Generate Photo Error: {e}")
        return None, None, None

async def generate_video(
    photo_url: str,
    prompt: str,
    model: str,
    motion_video_url: Optional[str] = None
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    try:
        logging.info("--- 🎬 VK Видео-генерация: %s ---", model)

        if model == "kling_motion_720":
            engine = KlingMotionControl(mode="720p")
            return await engine.generate(prompt, char_image_url=photo_url, motion_video_url=motion_video_url)

        elif model == "kling_motion_1080":
            engine = KlingMotionControl(mode="1080p")
            return await engine.generate(prompt, char_image_url=photo_url, motion_video_url=motion_video_url)

        return None, None, None
    except Exception as e:
        logging.error(f"❌ VK Generate Video Error: {e}")
        return None, None, None
