"""VK File Handler - Download and manage files from VK"""
import logging
from typing import Optional, Tuple
import aiohttp
from app.network import get_connector

logger = logging.getLogger(__name__)


async def download_vk_photo(photo_url: str) -> Tuple[Optional[bytes], str]:
    """Download photo from VK URL"""
    try:
        timeout = aiohttp.ClientTimeout(total=120, connect=30)
        max_size = 50 * 1024 * 1024  # 50MB max

        logger.info(f"📥 Downloading VK photo...")

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            async with session.get(photo_url) as resp:
                if resp.status != 200:
                    logger.error(f"❌ VK photo download status={resp.status}")
                    return None, ""

                data = bytearray()
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    data.extend(chunk)
                    if len(data) > max_size:
                        logger.error(f"❌ File size exceeded: {len(data)} bytes")
                        return None, ""

                mime = resp.content_type or "image/jpeg"
                return bytes(data), mime

    except Exception as e:
        logger.error(f"❌ Error downloading VK photo: {e}")
        return None, ""


async def download_vk_video(video_url: str) -> Tuple[Optional[bytes], str]:
    """Download video from VK URL"""
    try:
        timeout = aiohttp.ClientTimeout(total=600, connect=30)
        max_size = 500 * 1024 * 1024  # 500MB max

        logger.info(f"📥 Downloading VK video...")

        async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout) as session:
            async with session.get(video_url) as resp:
                if resp.status != 200:
                    logger.error(f"❌ VK video download status={resp.status}")
                    return None, ""

                data = bytearray()
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    data.extend(chunk)
                    if len(data) > max_size:
                        logger.error(f"❌ Video size exceeded: {len(data)} bytes")
                        return None, ""

                mime = "video/mp4"
                return bytes(data), mime

    except Exception as e:
        logger.error(f"❌ Error downloading VK video: {e}")
        return None, ""


def bytes_to_base64_data_uri(data: bytes, mime: str) -> str:
    """Convert bytes to base64 data URI"""
    import base64
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{b64}"
