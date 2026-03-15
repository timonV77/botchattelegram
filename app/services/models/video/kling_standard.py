import asyncio
import logging
import aiohttp
from typing import Optional, Tuple
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes


def _as_dict(payload):
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return {}


def _normalize_urls(image_urls):
    if image_urls is None:
        return []
    if isinstance(image_urls, str):
        image_urls = [image_urls]
    elif isinstance(image_urls, dict):
        image_urls = [image_urls.get("url") or image_urls.get("data")]
    elif not isinstance(image_urls, list):
        return []

    out = []
    for x in image_urls:
        if isinstance(x, str):
            s = x.strip()
            if s.startswith("http://") or s.startswith("https://"):
                out.append(s)
        elif isinstance(x, dict):
            s = x.get("url") or x.get("data")
            if isinstance(s, str):
                s = s.strip()
                if s.startswith("http://") or s.startswith("https://"):
                    out.append(s)
    # По доке Kling: от 0 до 2 референсов
    return out[:2]


class KlingStandard:
    def __init__(self):
        self.model_id = "kling/v3"
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json"
        }

    async def generate(self, prompt: str, image_urls=None, duration="5") -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
        try:
            # Ограничение промпта по доке (до 2500 символов)
            prompt = prompt[:2500]

            # Сервер строго требует строку для duration ("5" или "10")
            duration_str = str(duration)

            payload_input = {
                "prompt": prompt,
                "duration": duration_str,
                "aspect_ratio": "16:9",
                "mode": "std",
                "sound": "false"  # Строго строка
            }

            # Обработка референсов
            urls = _normalize_urls(image_urls)
            if urls:
                payload_input["images"] = [{"type": "url", "data": u} for u in urls]
                logging.info(f"Kling images_count={len(payload_input['images'])}")

            payload = {
                "model": self.model_id,
                "input": payload_input,
                "async": True
            }

            async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
                logging.info(f"🎬 Запуск Kling Standard (Duration: {duration_str}s)")
                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        logging.error(f"❌ Kling API Error: {await resp.text()}")
                        return None, None, None

                    raw_data = await resp.json(content_type=None)
                    data = _as_dict(raw_data)
                    request_id = data.get("id") or data.get("request_id")

                    if not request_id:
                        logging.error(f"❌ Kling request_id не найден. raw={raw_data}")
                        return None, None, None

                # Polling: ждём генерацию (до 10 минут)
                for attempt in range(60):
                    await asyncio.sleep(10)
                    async with session.get(f"{BASE_URL}/media/{request_id}", headers=self.headers) as r:
                        if r.status != 200:
                            continue

                        raw_res = await r.json(content_type=None)
                        res = _as_dict(raw_res)
                        status = res.get("status")

                        if status == "completed":
                            data_obj = _as_dict(res.get("data"))
                            final_url = data_obj.get("url") or res.get("url")
                            if not final_url:
                                outputs = res.get("outputs")
                                if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
                                    final_url = outputs[0].get("url")

                            if not final_url:
                                logging.error(f"❌ Kling completed без url. raw={raw_res}")
                                return None, None, None

                            # Скачиваем результат
                            vid_bytes = await _download_content_bytes(session, final_url)
                            return vid_bytes, "mp4", None

                        if status in ("failed", "error", "cancelled"):
                            logging.error(f"❌ Kling Failed: {res.get('error')} | raw={raw_res}")
                            break

        except Exception as e:
            logging.error(f"❌ Kling Exception: {e}")

        return None, None, None