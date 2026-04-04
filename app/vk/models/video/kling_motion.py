import asyncio
import logging
import aiohttp
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes, upload_file_smart


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
        motion_video_url: видео с эталонным движением (уже свежий URL через VK API).
        orientation: 'image' (до 10с) или 'video' (до 30с).
        """
        import time
        
        public_image_url = None
        public_video_url = None

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as dlsession:
            # 1. Скачиваем и перезаливаем фото персонажа
            try:
                async with dlsession.get(char_image_url) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        ct = resp.headers.get("Content-Type", "").lower()
                        logging.info(f"📥 Image downloaded: {len(img_bytes)} bytes, content-type: {ct}")
                        
                        if not img_bytes or len(img_bytes) < 500:
                            logging.error(f"❌ Фото слишком маленькое ({len(img_bytes)} bytes)")
                            return None, None, None
                        
                        # Уникальное имя файла для обхода кеша Catbox
                        unique_name = f"char_{int(time.time())}.jpg"
                        public_image_url = await upload_file_smart(img_bytes, filename=unique_name)
                    else:
                        logging.error(f"❌ Не удалось скачать фото. Status: {resp.status}")
                        return None, None, None
            except Exception as e:
                logging.error(f"❌ Ошибка при скачивании фото: {e}")
                return None, None, None

            # 2. Скачиваем и перезаливаем видео
            try:
                async with dlsession.get(motion_video_url) as resp:
                    if resp.status == 200:
                        video_bytes = await resp.read()
                        ct = resp.headers.get("Content-Type", "").lower()
                        logging.info(f"📥 Video downloaded: {len(video_bytes)} bytes, content-type: {ct}")
                        
                        # Проверяем что это видео, а не HTML-страница
                        if "text/html" in ct:
                            logging.error(f"❌ Видео URL вернул HTML вместо файла! URL: {motion_video_url[:100]}...")
                            return None, None, None
                        
                        if not video_bytes or len(video_bytes) < 1000:
                            logging.error(f"❌ Видео слишком маленькое ({len(video_bytes)} bytes)")
                            return None, None, None
                        
                        unique_name = f"motion_{int(time.time())}.mp4"
                        public_video_url = await upload_file_smart(video_bytes, filename=unique_name)
                    else:
                        logging.error(f"❌ Не удалось скачать видео. Status: {resp.status}")
                        return None, None, None
            except Exception as e:
                logging.error(f"❌ Ошибка при скачивании видео: {e}")
                return None, None, None

        if not public_image_url or not public_video_url:
            logging.error("❌ Не удалось подготовить публичные ссылки.")
            return None, None, None
        
        logging.info(f"📎 Image URL (re-uploaded): {public_image_url}")
        logging.info(f"📎 Video URL (re-uploaded): {public_video_url}")

        payload_input = {
            "prompt": prompt or "Character animation based on reference video",
            "mode": self.mode,
            "character_orientation": orientation,
            "images": [{"type": "url", "data": public_image_url}],
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
                
                request_id = None
                for attempt in range(3):
                    async with session.post(f"{BASE_URL}/media", headers=self.headers, json=payload) as resp:
                        if resp.status in (200, 201):
                            data = await resp.json()
                            request_id = data.get("id")
                            break
                        
                        resp_text = await resp.text()
                        # Если сервер перегружен (502, 503, 504) — пробуем еще раз
                        if resp.status in (502, 503, 504) and attempt < 2:
                            logging.warning(f"⚠️ Polza AI server error ({resp.status}), retry {attempt+1}/3...")
                            await asyncio.sleep(5)
                            continue
                        
                        logging.error(f"❌ Motion Control Error: {resp_text}")
                        return None, None, None

                if not request_id: return None, None, None

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