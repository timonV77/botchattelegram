import asyncio
import logging
import aiohttp
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes


def _as_dict(payload):
    """Нормализует payload к dict, если API иногда возвращает list[dict]."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return {}


class NanoBanana:
    def __init__(self, is_pro: bool = False):
        self.model_id = "google/gemini-2.5-flash-image" if not is_pro else "google/gemini-3-pro-image-preview"
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json"
        }

    async def generate(self, prompt: str, image_urls: list = None):
        payload_input = {
            "prompt": prompt,
            "aspect_ratio": "1:1",
            "output_format": "png"
        }

        if image_urls:
            valid_urls = image_urls[:8]
            payload_input["images"] = [{"type": "url", "data": url} for url in valid_urls]

        payload = {
            "model": self.model_id,
            "input": payload_input,
            "async": True
        }

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
            try:
                logging.info("🍌 Nano Banana Request: %s", self.model_id)

                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        err = await resp.text()
                        logging.error("❌ Nano Banana Start Error: %s", err)
                        return None, None, None

                    raw_data = await resp.json(content_type=None)
                    data = _as_dict(raw_data)
                    request_id = data.get("id") or data.get("request_id")

                    if not request_id:
                        logging.error("❌ Nano Banana: не найден request_id. raw=%r", raw_data)
                        return None, None, None

                for _ in range(40):
                    await asyncio.sleep(4)

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
                                # fallback: иногда может быть массив outputs
                                outputs = res.get("outputs")
                                if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
                                    final_url = outputs[0].get("url")

                            if not final_url:
                                logging.error("❌ Nano Banana completed без url. raw=%r", raw_res)
                                return None, None, None

                            return await _download_content_bytes(session, final_url)

                        if status in ("failed", "cancelled"):
                            logging.error("❌ Nano Banana Failed: %s | raw=%r", res.get("error"), raw_res)
                            break

            except Exception as e:
                logging.error("❌ Nano Banana Exception: %s", e)

        return None, None, None