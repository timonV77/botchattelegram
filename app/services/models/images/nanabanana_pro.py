import asyncio
import logging
import aiohttp
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes


class NanoBananaPro:
    def __init__(self, is_pro: bool = False):
        self.is_pro = is_pro
        # Используем актуальные ID из документации
        self.model_id = "google/gemini-3-pro-image-preview" if is_pro else "google/gemini-2.5-flash-image"
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json"
        }

    async def generate(self, prompt: str, image_urls: list = None, resolution: str = "1K", aspect_ratio: str = "1:1"):
        """
        Генерация изображения.
        resolution: '1K', '2K', '4K' (только для Pro)
        aspect_ratio: '1:1', '16:9', 'auto' (auto только для Pro)
        """

        # Базовые параметры
        payload_input = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio if self.is_pro or aspect_ratio != "auto" else "1:1",
            "output_format": "png"
        }

        # Специфичные параметры для Pro версии
        if self.is_pro:
            payload_input["image_resolution"] = resolution
            # Если в Pro версии не задан aspect_ratio, можно ставить auto
            if not aspect_ratio:
                payload_input["aspect_ratio"] = "auto"

        # Обработка референсов (до 8 штук)
        if image_urls:
            payload_input["images"] = [
                {"type": "url", "data": url} for url in image_urls[:8]
            ]

        payload = {
            "model": self.model_id,
            "input": payload_input,
            "async": True
        }

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
            try:
                logging.info(f"🍌 Nano Banana {'PRO' if self.is_pro else 'Base'} Request")
                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        logging.error(f"❌ API Error: {await resp.text()}")
                        return None, None, None

                    data = await resp.json()
                    request_id = data.get("id")

                # Polling
                # Pro-версия (особенно 4K) может генерироваться дольше, увеличим лимит
                max_attempts = 60 if self.is_pro else 30
                for _ in range(max_attempts):
                    await asyncio.sleep(5)
                    async with session.get(f"{BASE_URL}/media/{request_id}", headers=self.headers) as r:
                        if r.status != 200: continue
                        res = await r.json()
                        status = res.get("status")

                        if status == "completed":
                            final_url = res.get("data", {}).get("url")
                            return await _download_content_bytes(session, final_url)

                        if status in ("failed", "error"):
                            logging.error(f"❌ Generation failed: {res.get('error')}")
                            break

            except Exception as e:
                logging.error(f"❌ Exception in NanoBanana: {e}")

        return None, None, None