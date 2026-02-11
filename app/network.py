import os
import aiohttp
import asyncio
import logging
from typing import Tuple, Optional, List
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://api.polza.ai/api/v1"

# Карта моделей
MODELS_MAP = {
    "nanabanana": "nano-banana",
    "nanabanana_pro": "gemini-3-pro-image-preview",
    "seedream": "seedream-v4.5",
    "kling_5": "kling2.5-image-to-video",
    "kling_10": "kling2.5-image-to-video"
}

# Настройка таймаутов: общее время 10 минут, чтение данных 5 минут
timeout_config = aiohttp.ClientTimeout(total=600, connect=30, sock_read=300)


def get_connector():
    # Отключаем проверку SSL для стабильности скачивания медиафайлов
    return aiohttp.TCPConnector(ssl=False)


async def _download_content_bytes(session: aiohttp.ClientSession, url: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Скачивание готового файла (фото/видео) в байтах"""
    try:
        logging.info(f"📥 Начинаю скачивание готового файла: {url[:60]}...")
        async with session.get(url) as response:
            if response.status != 200:
                logging.error(f"❌ Ошибка скачивания (HTTP {response.status})")
                return None, None

            data = await response.read()
            content_type = response.headers.get("Content-Type", "").lower()
            ext = "mp4" if "video" in content_type else "jpg"
            logging.info(f"✅ Файл успешно скачан. Размер: {len(data)} байт")
            return data, ext
    except Exception as e:
        logging.error(f"❌ Критическая ошибка при скачивании файла: {e}")
        return None, None


# ================= IMAGE GENERATION =================

async def process_with_polza(prompt: str, model_type: str, image_urls: List[str] = None):
    if not POLZA_API_KEY:
        logging.error("❌ Ключ POLZA_API_KEY не найден в .env")
        return None, None

    model_id = MODELS_MAP.get(model_type, "nano-banana")
    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    # Подготовка полезной нагрузки
    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "aspect_ratio": "1:1",
        "resolution": "1K"
    }

    # ВАЖНО: Если передана одна ссылка, отправляем как строку (иногда API капризничает на списки)
    if image_urls:
        payload["filesUrl"] = image_urls

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            logging.info(f"📤 [API POST] Отправка запроса. Модель: {model_id}")
            async with session.post(f"{BASE_URL}/images/generations", headers=headers, json=payload) as response:
                res_text = await response.text()

                if response.status not in (200, 201):
                    logging.error(f"❌ Ошибка API Polza ({response.status}): {res_text}")
                    return None, None

                data = await response.json()
                request_id = data.get("requestId")
                if not request_id:
                    logging.error(f"❌ Поле requestId отсутствует в ответе: {data}")
                    return None, None

            logging.info(f"🔑 Запрос принят. ID: {request_id}. Начинаю опрос статуса...")

            # Цикл опроса готовности (Polling)
            for attempt in range(1, 101):  # до ~15 минут ожидания
                await asyncio.sleep(10)  # Проверка каждые 10 секунд

                async with session.get(f"{BASE_URL}/images/{request_id}", headers=headers) as resp:
                    if resp.status != 200:
                        logging.warning(f"📡 Попытка {attempt}: Ошибка связи (HTTP {resp.status})")
                        continue

                    result = await resp.json()
                    status = str(result.get("status", "")).lower()

                    logging.info(f"📡 Попытка {attempt}: Статус нейросети -> [{status}]")

                    if status == "success" or result.get("url") or result.get("images"):
                        # Пробуем вытащить URL из разных возможных полей API
                        url = result.get("url")
                        if not url and result.get("images") and len(result.get("images")) > 0:
                            url = result.get("images")[0]

                        if url:
                            logging.info(f"🎯 Фото готово! Перехожу к загрузке.")
                            return await _download_content_bytes(session, url)
                        else:
                            logging.error(f"❌ Статус 'success', но URL картинки не найден: {result}")
                            return None, None

                    if status in ("failed", "error", "canceled"):
                        # Ключевой момент для диагностики: выводим весь JSON ошибки
                        logging.error(f"❌ ГЕНЕРАЦИЯ ПРОВАЛЕНА API. Полный ответ: {result}")
                        break

            logging.warning("⌛ Превышено время ожидания генерации (таймаут 100 попыток).")

        except Exception as e:
            logging.error(f"❌ Сетевое исключение в process_with_polza: {e}")

    return None, None


# ================= VIDEO GENERATION =================

async def process_video_polza(prompt: str, model_type: str, image_url: str = None):
    if not POLZA_API_KEY:
        return None, None

    model_id = MODELS_MAP.get(model_type, "kling2.5-image-to-video")
    duration = 10 if model_type == "kling_10" else 5

    headers = {
        "Authorization": f"Bearer {POLZA_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_id,
        "prompt": prompt.strip(),
        "duration": duration,
        "cfgScale": 0.5
    }
    if image_url:
        payload["imageUrls"] = [image_url]

    async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
        try:
            logging.info(f"📤 [VIDEO POST] Запуск видео. Модель: {model_id}")
            async with session.post(f"{BASE_URL}/videos/generations", headers=headers, json=payload) as response:
                if response.status not in (200, 201):
                    return None, None
                data = await response.json()
                request_id = data.get("requestId")
                if not request_id: return None, None

            for attempt in range(1, 151):
                await asyncio.sleep(12)
                async with session.get(f"{BASE_URL}/videos/{request_id}", headers=headers) as resp:
                    if resp.status != 200: continue
                    result = await resp.json()
                    status = str(result.get("status", "")).lower()

                    logging.info(f"📡 Видео статус -> [{status}] (попытка {attempt})")

                    if status == "success":
                        url = result.get("url") or result.get("videoUrl")
                        if url:
                            return await _download_content_bytes(session, url)

                    if status in ("failed", "error"):
                        logging.error(f"❌ Генерация видео провалена: {result}")
                        break
        except Exception as e:
            logging.error(f"❌ Ошибка видео-модуля: {e}")

    return None, None