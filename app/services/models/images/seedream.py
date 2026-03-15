import asyncio
import logging
import aiohttp
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes


class Seedream:
    def __init__(self):
        self.model_id = "bytedance/seedream-4.5"
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json"
        }

    async def generate(self, prompt: str, image_urls: list = None, quality: str = "basic", aspect_ratio: str = "1:1"):
        """
        Генерация изображения через Seedream 4.5.
        quality: 'basic' (2K), 'high' (4K)
        aspect_ratio: '1:1', '16:9', '21:9', etc.
        """
        # Базовые параметры
        # У этой модели prompt, aspect_ratio и quality являются ОБЯЗАТЕЛЬНЫМИ
        payload_input = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "quality": quality
        }

        # Обработка референсов (до 14 штук)
        if image_urls:
            # Ограничиваем до 14 штук согласно лимитам модели
            valid_urls = image_urls[:14]
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
                logging.info(f"🌊 Seedream Request (Quality: {quality})")
                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        logging.error(f"❌ Seedream Error: {await resp.text()}")
                        return None, None, None

                    data = await resp.json()
                    request_id = data.get("id")

                # Polling: Seedream довольно быстрая (проверка каждые 5 сек)
                for attempt in range(40):  # До ~200 секунд
                    await asyncio.sleep(5)
                    async with session.get(f"{BASE_URL}/media/{request_id}", headers=self.headers) as r:
                        if r.status != 200: continue
                        res = await r.json()
                        status = res.get("status")

                        if status == "completed":
                            # Ссылка в data.url по документации GET Media Status
                            final_url = res.get("data", {}).get("url")
                            return await _download_content_bytes(session, final_url)

                        if status in ("failed", "cancelled"):
                            logging.error(f"❌ Seedream Failed: {res.get('error')}")
                            break

            except Exception as e:
                logging.error(f"❌ Seedream Exception: {e}")

        return None, None, None