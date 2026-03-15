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
    # По доке Seedream лимит - 14 референсов
    return out[:14]


class Seedream:
    def __init__(self):
        self.model_id = "bytedance/seedream-4.5"
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json"
        }

    async def generate(self, prompt: str, image_urls=None, quality: str = "basic", aspect_ratio: str = "1:1") -> Tuple[
        Optional[bytes], Optional[str], Optional[str]]:
        # Ограничение промпта по доке (до 3000 символов)
        prompt = prompt[:3000]

        payload_input = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "quality": quality
        }

        # Обработка референсов
        urls = _normalize_urls(image_urls)
        if urls:
            payload_input["images"] = [{"type": "url", "data": u} for u in urls]
            logging.info("Seedream images_count=%s", len(payload_input["images"]))

        payload = {
            "model": self.model_id,
            "input": payload_input,
            "async": True
        }

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
            try:
                logging.info("🌊 Seedream Request (Quality: %s)", quality)
                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        logging.error("❌ Seedream Error: %s", await resp.text())
                        return None, None, None

                    raw_data = await resp.json(content_type=None)
                    data = _as_dict(raw_data)
                    request_id = data.get("id") or data.get("request_id")

                    if not request_id:
                        logging.error("❌ Seedream request_id не найден. raw=%r", raw_data)
                        return None, None, None

                # Polling: Seedream довольно быстрая (проверка каждые 5 сек)
                for attempt in range(40):  # До ~200 секунд
                    await asyncio.sleep(5)
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
                                logging.error("❌ Seedream completed без url. raw=%r", raw_res)
                                return None, None, None

                            return await _download_content_bytes(session, final_url)

                        if status in ("failed", "error", "cancelled"):
                            logging.error("❌ Seedream Failed: %s | raw=%r", res.get("error"), raw_res)
                            break

            except Exception as e:
                logging.error("❌ Seedream Exception: %s", e)

        return None, None, None