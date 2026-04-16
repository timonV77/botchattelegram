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
    """Upload small files (up to 5MB) to Telegraph"""
    try:
        form = aiohttp.FormData()
        content_type = 'video/mp4' if filename and filename.endswith('.mp4') else 'image/jpeg'
        form.add_field('file', file_bytes, filename=filename or 'file.jpg', content_type=content_type)
        
        # Короткий таймаут — telegra.ph может быть недоступен
        timeout = aiohttp.ClientTimeout(total=8, connect=4, sock_read=6)
        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            async with session.post('https://telegra.ph/upload', data=form) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return f"https://telegra.ph{data[0].get('src')}"
                else:
                    logging.warning(f"⚠️ Telegraph upload failed: status={resp.status}")
    except Exception as e:
        logging.error(f"❌ Ошибка Telegraph: {e}")
    return None


async def upload_file_to_0x0(file_bytes: bytes, filename: str = None) -> Optional[str]:
    """Upload to 0x0.st (no auth, up to 512MB, permanent)"""
    try:
        upload_filename = filename or 'image.jpg'
        content_type = 'video/mp4' if upload_filename.endswith('.mp4') else 'image/jpeg'
        form = aiohttp.FormData()
        form.add_field('file', file_bytes, filename=upload_filename, content_type=content_type)
        timeout = aiohttp.ClientTimeout(total=30, connect=8, sock_read=20)
        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            logging.info(f"📤 Загрузка файла в 0x0.st ({upload_filename})...")
            async with session.post('https://0x0.st', data=form) as resp:
                if resp.status == 200:
                    url = (await resp.text()).strip()
                    if url.startswith('http'):
                        logging.info(f"✅ 0x0.st URL: {url}")
                        return url
                else:
                    logging.warning(f"⚠️ 0x0.st upload failed: status={resp.status}")
    except Exception as e:
        logging.warning(f"⚠️ Ошибка 0x0.st: {e}")
    return None


async def upload_file_to_litterbox(file_bytes: bytes, filename: str = None) -> Optional[str]:
    """Upload to litterbox.catbox.moe (temporary, 72h, no auth)"""
    try:
        upload_filename = filename or 'image.jpg'
        content_type = 'video/mp4' if upload_filename.endswith('.mp4') else 'image/jpeg'
        form = aiohttp.FormData()
        form.add_field('reqtype', 'fileupload')
        form.add_field('time', '72h')
        form.add_field('fileToUpload', file_bytes, filename=upload_filename, content_type=content_type)
        timeout = aiohttp.ClientTimeout(total=30, connect=8, sock_read=20)
        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            logging.info(f"📤 Загрузка файла в Litterbox ({upload_filename})...")
            async with session.post('https://litterbox.catbox.moe/resources/internals/api.php', data=form) as resp:
                if resp.status == 200:
                    url = (await resp.text()).strip()
                    if url.startswith('http'):
                        logging.info(f"✅ Litterbox URL: {url}")
                        return url
                else:
                    logging.warning(f"⚠️ Litterbox upload failed: status={resp.status}")
    except Exception as e:
        logging.warning(f"⚠️ Ошибка Litterbox: {e}")
    return None


async def upload_file_smart(file_bytes: bytes, filename: str = None) -> Optional[str]:
    """Перебирает все доступные хосты по очереди: Telegraph → Catbox → 0x0.st → Litterbox"""
    size_mb = len(file_bytes) / (1024 * 1024)

    # Telegraph только для маленьких файлов
    if size_mb < 3.5:
        url = await upload_file_to_host(file_bytes, filename)
        if url:
            return url
        logging.warning("⚠️ Telegraph недоступен, пробуем Catbox...")

    url = await upload_file_to_catbox(file_bytes, filename=filename)
    if url:
        return url

    logging.warning("⚠️ Catbox недоступен, пробуем 0x0.st...")
    url = await upload_file_to_0x0(file_bytes, filename=filename)
    if url:
        return url

    logging.warning("⚠️ 0x0.st недоступен, пробуем Litterbox...")
    url = await upload_file_to_litterbox(file_bytes, filename=filename)
    if url:
        return url

    logging.error("❌ Все хосты для загрузки файлов недоступны")
    return None


async def upload_file_to_catbox(file_bytes: bytes, filename: str = None) -> Optional[str]:
    """Upload larger files (up to 200MB) to Catbox.moe"""
    try:
        if filename and filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            upload_filename = filename
            content_type = 'image/jpeg' if filename.lower().endswith(('.jpg', '.jpeg')) else 'image/png'
        else:
            upload_filename = filename or 'motion_ref.mp4'
            content_type = 'video/mp4'

        form = aiohttp.FormData()
        form.add_field('reqtype', 'fileupload')
        form.add_field('fileToUpload', file_bytes, filename=upload_filename, content_type=content_type)

        timeout = aiohttp.ClientTimeout(total=30, connect=8, sock_read=20)
        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            logging.info(f"📤 Загрузка файла в Catbox.moe ({upload_filename})...")
            async with session.post('https://catbox.moe/user/api.php', data=form) as resp:
                if resp.status == 200:
                    url = (await resp.text()).strip()
                    if url.startswith('http'):
                        logging.info(f"✅ Catbox URL: {url}")
                        return url
                else:
                    logging.warning(f"⚠️ Catbox upload failed: status={resp.status}")
    except Exception as e:
        logging.warning(f"⚠️ Ошибка Catbox: {e}")
    return None