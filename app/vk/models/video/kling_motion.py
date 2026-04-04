import asyncio
import logging
import aiohttp
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes, upload_file_to_host


class KlingMotionControl:
    def __init__(self, mode: str = "720p"):
        self.model_id = "kling/v2.6-motion-control"
        self.mode = mode  # "720p" или "1080p"
        self.headers = {
            "Authorization": f"Bearer {POLZA_API_KEY}",
            "Content-Type": "application/json"
        }

    async def generate(self, prompt: str, char_image_url: str, motion_video_url: str, orientation: str = "image"):
        """
        Перенос движения с видео на фото.
        char_image_url: фото персонажа.
        motion_video_url: видео с эталонным движением.
        orientation: 'image' (до 10с) или 'video' (до 30с).
        """
        
        # 1. Скачиваем видео и заливаем на Telegraph для публичной ссылки
        # (API Polza.ai / Kling предпочитает URL для видео вместо Base64)
        public_video_url = None
        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as dlsession:
            async with dlsession.get(motion_video_url) as resp:
                if resp.status == 200:
                    video_bytes = await resp.read()
                    public_video_url = await upload_file_to_host(video_bytes, filename="motion_ref.mp4")
                else:
                    logging.error(f"❌ Не удалось скачать ВК-видео. Status: {resp.status}")
                    return None, None, None

        if not public_video_url:
            logging.error("❌ Не удалось получить публичную ссылку на видео.")
            return None, None, None

        payload_input = {
            "prompt": prompt or "Character animation based on reference video",
            "mode": self.mode,
            "character_orientation": orientation,
            "images": [{"type": "url", "data": char_image_url}],
            "videos": [{"type": "url", "data": public_video_url}]
        }

        payload = {
            "model": self.model_id,
            "input": payload_input,
            "async": True
        }

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as session:
            try:
                logging.info(f"💃 Kling Motion Control Start (Mode: {self.mode})")
                async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                    if resp.status not in (200, 201):
                        logging.error(f"❌ Motion Control Error: {await resp.text()}")
                        return None, None, None

                    data = await resp.json()
                    request_id = data.get("id")

                # Polling: Технология сложная, может занять время
                for attempt in range(120):  # До 20 минут
                    await asyncio.sleep(10)
                    async with session.get(f"{BASE_URL}/media/{request_id}", headers=self.headers) as r:
                        if r.status != 200: continue
                        res = await r.json()
                        status = res.get("status")

                        if status == "completed":
                            final_url = res.get("data", {}).get("url")
                            return await _download_content_bytes(session, final_url)

                        if status in ("failed", "cancelled"):
                            logging.error(f"❌ Motion Control Failed: {res.get('error')}")
                            break

            except Exception as e:
                logging.error(f"❌ Motion Control Exception: {e}")

        return None, None, None