import asyncio
import logging
import aiohttp
from typing import Optional, Tuple, List
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes


def _as_dict(payload):
    """Нормализует payload к dict, если API иногда возвращает list[dict]."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return {}


class GrokImagine:
    """Генерация изображений через Grok Imagine (x-ai/grok-imagine-image)."""

    def __init__(self):
        self.model_id = "x-ai/grok-imagine-image"
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json"
        }

    async def generate(
        self,
        prompt: str,
        image_urls: List[str] = None,
        aspect_ratio: str = "1:1",
    ) -> Tuple[Optional[List[bytes]], Optional[str], Optional[str]]:
        payload_input = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "images": [],
        }

        # Референсные изображения (если есть)
        if image_urls:
            valid_urls = image_urls[:1]
            logging.info(f"🤖 Grok Imagine: received {len(image_urls)} images, using {len(valid_urls)}")
            payload_input["images"] = [{"type": "url", "data": url} for url in valid_urls]

        payload = {
            "model": self.model_id,
            "input": payload_input,
            "async": True
        }

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
            try:
                logging.info("🤖 Grok Imagine Request: %s", self.model_id)

                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        err = await resp.text()
                        logging.error("❌ Grok Imagine Start Error: %s", err)
                        return None, None, None

                    raw_data = await resp.json(content_type=None)
                    data = _as_dict(raw_data)
                    request_id = data.get("id") or data.get("request_id")

                    if not request_id:
                        logging.error("❌ Grok Imagine: не найден request_id. raw=%r", raw_data)
                        return None, None, None

                # Polling: проверка каждые 4 секунды, до ~160 секунд
                for _ in range(40):
                    await asyncio.sleep(4)

                    async with session.get(f"{BASE_URL}/media/{request_id}", headers=self.headers) as r:
                        if r.status != 200:
                            continue

                        raw_res = await r.json(content_type=None)
                        res = _as_dict(raw_res)
                        status = res.get("status")

                        if status == "completed":
                            # Check for multiple outputs
                            outputs = res.get("outputs")
                            if isinstance(outputs, list) and outputs:
                                logging.info(f"🤖 Grok Imagine: received {len(outputs)} outputs")
                                result_images = []
                                for output in outputs:
                                    if isinstance(output, dict):
                                        url = output.get("url")
                                        if url:
                                            img_bytes, ext, mime = await _download_content_bytes(session, url)
                                            if img_bytes:
                                                result_images.append(img_bytes)

                                if result_images:
                                    return result_images, ext, mime

                            # Fallback to single image
                            data_obj = _as_dict(res.get("data"))
                            final_url = data_obj.get("url") or res.get("url")

                            if final_url:
                                img_bytes, ext, mime = await _download_content_bytes(session, final_url)
                                return [img_bytes] if img_bytes else None, ext, mime

                            logging.error("❌ Grok Imagine completed без url. raw=%r", raw_res)
                            return None, None, None

                        if status in ("failed", "error", "cancelled"):
                            logging.error("❌ Grok Imagine Failed: %s | raw=%r", res.get("error"), raw_res)
                            break

            except Exception as e:
                logging.error("❌ Grok Imagine Exception: %s", e)

        return None, None, None
