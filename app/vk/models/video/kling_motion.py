import asyncio
import logging
import aiohttp
from app.network import BASE_URL, POLZA_API_KEY, get_connector, timeout_config, _download_content_bytes



# VK doc video download strategies
_VK_DOC_DOWNLOAD_HEADERS = [
    # Стратегия 1: Прямой запрос как из браузера (navigate)
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://vk.com/",
    },
    # Стратегия 2: Как fetch-запрос видеоэлемента
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,*/*;q=0.5",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
        "Referer": "https://vk.com/",
    },
]

_VIDEO_MAGIC_BYTES = [
    b"\x00\x00\x00",   # MP4/MOV ISO base media
    b"ftyp",            # MP4 ftyp box
    b"\x1a\x45\xdf\xa3",  # WebM/MKV
    b"RIFF",            # AVI
    b"OggS",            # OGG
]


def _is_video_bytes(data: bytes) -> bool:
    """Проверяем magic bytes — это действительно видео-файл?"""
    if not data or len(data) < 16:
        return False
    # Проверяем первые 12 байт
    for magic in _VIDEO_MAGIC_BYTES:
        if data[:len(magic)] == magic:
            return True
    # MP4: 'ftyp' может быть на offsets 4-8
    if b"ftyp" in data[:20]:
        return True
    return False


async def _download_vk_doc_video(session: aiohttp.ClientSession, url: str) -> bytes | None:
    """
    Умное скачивание VK-документа с видео.
    VK хранит документы на CDN, но URL vk.ru/doc... может редиректить на HTML.
    Пробуем несколько стратегий с разными заголовками.
    """
    urls_to_try = [url]

    # Если URL на vk.ru — пробуем также vk.com версию
    if "vk.ru/doc" in url:
        urls_to_try.append(url.replace("vk.ru/doc", "vk.com/doc"))

    for try_url in urls_to_try:
        for headers in _VK_DOC_DOWNLOAD_HEADERS:
            try:
                async with session.get(try_url, headers=headers, allow_redirects=True, max_redirects=10) as resp:
                    if resp.status != 200:
                        logging.warning(f"⚠️ VK doc download status={resp.status} for {try_url[:80]}")
                        continue

                    ct = resp.headers.get("Content-Type", "").lower()
                    data = await resp.read()

                    if "text/html" in ct:
                        import re
                        html_text = data.decode("utf-8", errors="ignore")
                        
                        # Ищем ЛЮБУЮ прямую ссылку на медиаконтент в HTML
                        # 1. userapi.com (все поддомены: sun9, psv4 и т.д.)
                        # 2. ИЛИ содержит /doc и vk.
                        # 3. ИЛИ заканчивается на .mp4
                        pattern = r'(?:src|href|URL|url|action)=[\'"]?(https://[^\s\'">]+(?:userapi\.com|vk\.(?:com|ru)/(?:doc|video_ext)|vnd\.vk\.com|/[^\s\'">]+\.mp4)[^\s\'">]*)[\'"]?'
                        matches = set(re.findall(pattern, html_text))
                        
                        real_url = None
                        for m in matches:
                            # Игнорируем скрипты и стили
                            if not m.endswith((".js", ".css")):
                                real_url = m.replace("&amp;", "&")
                                break
                        
                        if real_url:
                            logging.info(f"🔄 Extracted real URL from VK HTML: {real_url[:80]}...")
                            try:
                                async with session.get(real_url, headers=headers, allow_redirects=True) as real_resp:
                                    if real_resp.status == 200:
                                        data = await real_resp.read()
                                        new_ct = real_resp.headers.get("Content-Type", "").lower()
                                        if "text/html" not in new_ct and len(data) >= 1000:
                                            if _is_video_bytes(data):
                                                logging.info(f"✅ VK doc video скачан после парсинга HTML: {len(data)} bytes")
                                                return data
                                            logging.info(f"📥 VK doc скачан после парсинга ({len(data)} bytes), принимаем без magic bytes")
                                            return data
                            except Exception as e:
                                logging.warning(f"⚠️ Ошибка при скачивании по извлеченному ссылке: {e}")
                        
                        logging.warning(f"⚠️ VK doc URL вернул HTML ({len(data)} bytes), парсинг не помог, пробуем другую стратегию...")
                        continue

                    if not data or len(data) < 1000:
                        logging.warning(f"⚠️ VK doc слишком маленький ({len(data)} bytes), пробуем другую стратегию...")
                        continue

                    if _is_video_bytes(data):
                        logging.info(f"✅ VK doc video скачан: {len(data)} bytes (strategy: {headers.get('Sec-Fetch-Dest', '?')})")
                        return data

                    # Данные пришли, но magic bytes не совпали — всё равно используем
                    # (разные контейнеры могут иметь другие сигнатуры)
                    logging.info(f"📥 VK doc скачан ({len(data)} bytes, ct={ct}) — принимаем без magic bytes валидации")
                    return data

            except Exception as e:
                logging.warning(f"⚠️ VK doc стратегия упала: {e}")
                continue

    logging.error(f"❌ Все стратегии скачивания VK doc исчерпаны. URL: {url[:120]}")
    return None


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
        # Полный набор браузерных заголовков для обхода защиты VK (не используем для статических фото)
        public_image_url = char_image_url
        public_video_url = motion_video_url

        if not public_image_url or not public_video_url:
            logging.error("❌ Не удалось подготовить публичные ссылки (пустые URL).")
            return None, None, None
        
        logging.info(f"📎 Image URL (native): {public_image_url}")
        logging.info(f"📎 Video URL (native): {public_video_url}")

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