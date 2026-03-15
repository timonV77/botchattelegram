import asyncio
import logging
import aiohttp
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes


class NanoBanana:
    def __init__(self, is_pro: bool = False):
        # Строго по документации Polza
        self.model_id = "google/gemini-2.5-flash-image" if not is_pro else "google/gemini-3-pro-image-preview"
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json"
        }

    async def generate(self, prompt: str, image_urls: list = None):
        """
        Генерация изображения через Nano Banana.
        Поддерживает до 8 референс-изображений.
        """
        payload_input = {
            "prompt": prompt,
            "aspect_ratio": "1:1",
            "output_format": "png"
        }

        if image_urls:
            # Ограничиваем до 8 штук согласно лимитам модели
            valid_urls = image_urls[:8]
            payload_input["images"] = [
                {"type": "url", "data": url} for url in valid_urls
            ]

        payload = {
            "model": self.model_id,
            "input": payload_input,
            "async": True
        }

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
            try:
                logging.info(f"🍌 Nano Banana Request: {self.model_id}")
                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        err = await resp.text()
                        logging.error(f"❌ Nano Banana Start Error: {err}")
                        return None, None, None

                    data = await resp.json()
                    request_id = data.get("id")

                # Polling (проверка статуса каждые 4 секунды)
                for attempt in range(40):  # Лимит ~160 секунд
                    await asyncio.sleep(4)
                    async with session.get(f"{BASE_URL}/media/{request_id}", headers=self.headers) as r:
                        if r.status != 200: continue
                        res = await r.json()
                        status = res.get("status")

                        if status == "completed":
                            # Важно: Ссылка в data['url'] по документации GET Media Status
                            final_url = res.get("data", {}).get("url")
                            return await _download_content_bytes(session, final_url)

                        if status in ("failed", "cancelled"):
                            logging.error(f"❌ Nano Banana Failed: {res.get('error')}")
                            break

            except Exception as e:
                logging.error(f"❌ Nano Banana Exception: {e}")

        return None, None, None