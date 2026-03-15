import asyncio
import logging
import aiohttp
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes


def _as_dict(payload):
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return {}


def _extract_b64(data_uri: str) -> str:
    # data:image/png;base64,XXXX -> XXXX
    if "," in data_uri:
        return data_uri.split(",", 1)[1]
    return data_uri


class NanoBananaPro:
    def __init__(self, is_pro: bool = False):
        self.is_pro = is_pro
        self.model_id = "google/gemini-3-pro-image-preview" if is_pro else "google/gemini-2.5-flash-image"
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json",
        }

    async def generate(self, prompt: str, image_urls: list = None, resolution: str = "1K", aspect_ratio: str = "1:1"):
        payload_input = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio if self.is_pro or aspect_ratio != "auto" else "1:1",
            "output_format": "png",
        }

        if self.is_pro:
            payload_input["image_resolution"] = resolution
            if not aspect_ratio:
                payload_input["aspect_ratio"] = "auto"

        if image_urls:
            payload_input["images"] = []
            for src in image_urls[:8]:
                if not isinstance(src, str):
                    continue

                if src.startswith("data:image/"):
                    # отправляем чистый base64
                    payload_input["images"].append({
                        "type": "base64",
                        "data": _extract_b64(src)
                    })
                elif src.startswith("http://") or src.startswith("https://"):
                    payload_input["images"].append({
                        "type": "url",
                        "data": src
                    })

        logging.info("NanoBananaPro images_count=%s", len(payload_input.get("images", [])))

        payload = {
            "model": self.model_id,
            "input": payload_input,
            "async": True,
        }

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
            try:
                logging.info("🍌 Nano Banana %s Request", "PRO" if self.is_pro else "Base")

                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        logging.error("❌ API Error: %s", await resp.text())
                        return None, None, None

                    raw_data = await resp.json(content_type=None)
                    data = _as_dict(raw_data)
                    request_id = data.get("id") or data.get("request_id")

                    if not request_id:
                        logging.error("❌ NanoBananaPro: request_id не найден. raw=%r", raw_data)
                        return None, None, None

                max_attempts = 60 if self.is_pro else 30
                for _ in range(max_attempts):
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
                                logging.error("❌ NanoBananaPro completed без url. raw=%r", raw_res)
                                return None, None, None

                            return await _download_content_bytes(session, final_url)

                        if status in ("failed", "error", "cancelled"):
                            logging.error("❌ Generation failed: %s | raw=%r", res.get("error"), raw_res)
                            break

            except Exception as e:
                logging.error("❌ Exception in NanoBananaPro: %s", e)

        return None, None, None