import aiohttp
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

async def get_direct_video_and_upload(video_id: str) -> Optional[str]:
    """
    1. Делает запрос в video.get с user_token.
    2. Выбирает mp4_720, mp4_480 или mp4_360.
    3. Скачивает во временное хранилище.
    4. Загружает на Catbox.moe.
    5. Возвращает прямую .mp4 ссылку.
    """
    user_token = settings.vk_user_token
    if not user_token:
        logger.error("❌ vk_user_token is not set. Cannot get direct video link.")
        return None

    # Шаг 1: Получаем прямую ссылку из ВК через video.get
    logger.info(f"🔄 Получение прямой ссылки для видео {video_id}...")
    vk_api_url = "https://api.vk.com/method/video.get"
    params = {
        "videos": video_id,
        "access_token": user_token,
        "v": "5.199"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(vk_api_url, params=params) as resp:
                data = await resp.json()
                
                if "error" in data:
                    logger.error(f"❌ Ошибка VK API (video.get): {data['error']}")
                    return None
                
                items = data.get("response", {}).get("items", [])
                if not items:
                    logger.error("❌ VK API не вернул видео.")
                    return None

                video_item = items[0]
                files = video_item.get("files")
                if not files:
                    logger.error("❌ В ответе нет поля files (возможно, видео приватное).")
                    return None

                # Шаг 2: Выбираем максимальное качество
                mp4_url = files.get("mp4_720") or files.get("mp4_480") or files.get("mp4_360") or files.get("mp4_240")
                if not mp4_url:
                    logger.error("❌ В объекте files нет mp4 ссылок.")
                    return None

                logger.info(f"✅ Прямая ссылка получена: {mp4_url[:80]}...")

                # Шаг 3: Скачивание (Proxy)
                logger.info("⬇️ Скачивание файла...")
                async with session.get(mp4_url) as file_resp:
                    if file_resp.status != 200:
                        logger.error(f"❌ Ошибка скачивания: {file_resp.status}")
                        return None
                    video_bytes = await file_resp.read()

                # Шаг 4: Загрузка на Catbox.moe
                logger.info("⬆️ Загрузка на Catbox...")
                form_data = aiohttp.FormData()
                form_data.add_field('reqtype', 'fileupload')
                form_data.add_field('fileToUpload', video_bytes, filename='video.mp4', content_type='video/mp4')

                async with session.post("https://catbox.moe/user/api.php", data=form_data) as upload_resp:
                    if upload_resp.status != 200:
                        logger.error(f"❌ Ошибка загрузки на Catbox: {upload_resp.status}")
                        return None
                    catbox_url = await upload_resp.text()

                logger.info(f"✅ Загрузка на Catbox завершена: {catbox_url}")
                return catbox_url

    except Exception as e:
        logger.error(f"❌ Exception in get_direct_video_and_upload: {e}")
        return None
