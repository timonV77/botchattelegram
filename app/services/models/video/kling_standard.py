import asyncio
import logging
import aiohttp
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes


class KlingStandard:
    def __init__(self):
        self.model_id = "kling/v3"
        self.mode = "std"  # Фиксируем стандартный режим
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json"
        }

    async def generate(self, prompt: str, image_urls: list = None, duration: int = 5, aspect_ratio: str = "16:9"):
        """
        Генерация видео в стандартном режиме.
        image_urls: если передан 1 URL, используется как Start Frame.
        """
        payload_input = {
            "prompt": prompt,
            "duration": duration,
            "mode": self.mode,
            "aspect_ratio": aspect_ratio,
            "sound": False  # В стандарте обычно звук не требуется, если не указано иное
        }

        # Обработка фото-референса (Image-to-Video)
        if image_urls:
            payload_input["images"] = [
                {"type": "url", "data": url} for url in image_urls[:1]  # Берем только первый кадр
            ]

        payload = {
            "model": self.model_id,
            "input": payload_input,
            "async": True
        }

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
            try:
                logging.info(f"🎬 Запуск Kling Standard (Prompt: {prompt[:30]}...)")
                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        logging.error(f"❌ Kling API Error: {await resp.text()}")
                        return None, None, None

                    data = await resp.json()
                    request_id = data.get("id")

                # Polling: Стандартное видео обычно готово за 2-5 минут
                for attempt in range(60):  # 60 попыток по 10 сек = 10 минут максимум
                    await asyncio.sleep(10)
                    async with session.get(f"{BASE_URL}/media/{request_id}", headers=self.headers) as r:
                        if r.status != 200: continue
                        res = await r.json()
                        status = res.get("status")

                        if status == "completed":
                            final_url = res.get("data", {}).get("url")
                            return await _download_content_bytes(session, final_url)

                        if status in ("failed", "cancelled"):
                            logging.error(f"❌ Kling Standard Failed: {res.get('error')}")
                            break

            except Exception as e:
                logging.error(f"❌ Kling Standard Exception: {e}")

        return None, None, None