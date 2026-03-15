import os
import aiohttp
import logging
from typing import Tuple, Optional
from dotenv import load_dotenv

load_dotenv()

POLZA_API_KEY = os.getenv("POLZA_API_KEY")
BASE_URL = "https://polza.ai/api/v1"
timeout_config = aiohttp.ClientTimeout(total=600, connect=30, sock_read=300)

def get_connector():
    return aiohttp.TCPConnector(ssl=False)

async def _download_content_bytes(session: aiohttp.ClientSession, url: str) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    try:
        target_url = url.get("url") if isinstance(url, dict) else url
        if not target_url or not isinstance(target_url, str):
            return None, None, str(url)

        async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=300)) as response:
            if response.status != 200: return None, None, target_url
            data = await response.read()
            content_type = response.headers.get("Content-Type", "").lower()
            ext = "mp4" if "video" in content_type else "jpg"
            return data, ext, target_url
    except Exception as e:
        logging.error(f"❌ Ошибка скачивания: {e}")
        return None, None, str(url)

async def upload_file_to_host(file_bytes: bytes, filename: str = None) -> Optional[str]:
    try:
        form = aiohttp.FormData()
        content_type = 'video/mp4' if filename and filename.endswith('.mp4') else 'image/jpeg'
        form.add_field('file', file_bytes, filename=filename or 'file.jpg', content_type=content_type)
        async with aiohttp.ClientSession(connector=get_connector()) as session:
            async with session.post('https://telegra.ph/upload', data=form) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return f"https://telegra.ph{data[0].get('src')}"
    except Exception as e:
        logging.error(f"❌ Ошибка Telegraph: {e}")
    return None