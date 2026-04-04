"""
vk_video_resolver.py — Получение прямой .mp4 ссылки на VK-видео.

Поддерживает два типа вложений, которые встречаются в боте:
  A) Документ (attachment.type == "doc", ext in ["mp4", "mov", ...])
     → URL вида https://vk.ru/doc<owner>_<id>?...
     → Его doc.url — прямая CDN-ссылка, но живёт ~1 час.

  B) Видео (attachment.type == "video")
     → Имеет owner_id, id, access_key
     → video.get с user_token → поле files → mp4_720/mp4_480/mp4_360

Стратегии в порядке приоритета:
  1. VK API video.get + user_token → files.mp4_XXX (только для собственных/загруженных видео)
  2. yt-dlp (если установлен) → universal, работает для любого видео ВК
  3. Прямая попытка скачать doc.url (для документов, пока URL ещё горячий)
"""
import asyncio
import logging
import os
import tempfile
from typing import Optional

import aiohttp

from app.config import settings
from app.network import get_connector

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# СТРАТЕГИЯ 1: VK API video.get → поле files
# Работает только для видео, загруженных через user_token владельца.
# Для чужих/пересланных видео поле files будет отсутствовать.
# ─────────────────────────────────────────────────────────────────
async def _resolve_via_vk_api(
    owner_id: int,
    video_id: int,
    access_key: Optional[str] = None,
) -> Optional[str]:
    """
    Запрашивает video.get с user_token и возвращает прямую mp4 ссылку из files.
    Требует VK_USER_TOKEN в .env (личный токен пользователя VK, не группы).
    """
    user_token = settings.vk_user_token
    if not user_token:
        logger.warning("⚠️  VK_USER_TOKEN не задан — стратегия VK API пропущена.")
        return None

    video_ref = f"{owner_id}_{video_id}"
    if access_key:
        video_ref += f"_{access_key}"

    params = {
        "videos": video_ref,
        "access_token": user_token,
        "v": "5.199",
    }

    try:
        async with aiohttp.ClientSession(connector=get_connector()) as session:
            async with session.get(
                "https://api.vk.com/method/video.get",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

        if "error" in data:
            err = data["error"]
            logger.warning(
                f"⚠️  VK API video.get error {err.get('error_code')}: {err.get('error_msg')}"
            )
            return None

        items = data.get("response", {}).get("items", [])
        if not items:
            logger.warning("⚠️  VK API video.get вернул пустой items.")
            return None

        files: dict = items[0].get("files") or {}
        if not files:
            # files отсутствует — скорее всего, чужое/приватное видео
            player_url = items[0].get("player", "")
            logger.warning(
                f"⚠️  VK API: поле files отсутствует. player={player_url[:80]!r}. "
                "Это нормально для чужих/пересланных видео. Переходим к yt-dlp."
            )
            return None

        # Выбираем наилучшее разрешение
        for quality in ("mp4_1080", "mp4_720", "mp4_480", "mp4_360", "mp4_240"):
            url = files.get(quality)
            if url:
                logger.info(f"✅ VK API: прямая ссылка ({quality}): {url[:80]}...")
                return url

        logger.warning(f"⚠️  VK API: files есть, но нет mp4 ссылок. files keys: {list(files.keys())}")
        return None

    except Exception as e:
        logger.error(f"❌ VK API video.get exception: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# СТРАТЕГИЯ 2: yt-dlp (универсально, включая чужие/пересланные видео)
# Устанавливается: pip install yt-dlp
# ─────────────────────────────────────────────────────────────────
async def _resolve_via_ytdlp(vk_video_url: str) -> Optional[str]:
    """
    Использует yt-dlp для извлечения прямой ссылки на mp4 из VK плеера.
    vk_video_url — canonical URL вида https://vk.com/video-12345_67890
    или https://vk.com/video-12345_67890?access_key=...

    Для приватных видео потребуется cookies. Экспортируйте cookies из браузера
    (где вы залогинены в VK) с помощью расширения 'Get cookies.txt LOCALLY'
    и укажите путь в VK_COOKIES_PATH в .env.
    """
    try:
        import yt_dlp  # noqa: F401 — проверяем, установлена ли библиотека
    except ImportError:
        logger.warning("⚠️  yt-dlp не установлен. Запустите: pip install yt-dlp")
        return None

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,              # Только извлекаем URL, не качаем
        "format": "bestvideo[ext=mp4]/best[ext=mp4]/best",
        "socket_timeout": 30,
    }

    # Если есть cookies-файл для приватных видео
    cookies_path = os.getenv("VK_COOKIES_PATH", "")
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts["cookiefile"] = cookies_path
        logger.info(f"🍪 yt-dlp: используем cookies из {cookies_path}")

    def _extract_sync(url: str) -> Optional[str]:
        """Синхронный вызов yt-dlp (запускаем в executor)."""
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None
                # Если это плейлист/список — берём первый
                if "entries" in info:
                    info = info["entries"][0]
                return info.get("url")
        except Exception as e:
            logger.warning(f"⚠️  yt-dlp extract_info error: {e}")
            return None

    try:
        loop = asyncio.get_event_loop()
        direct_url = await loop.run_in_executor(None, _extract_sync, vk_video_url)
        if direct_url:
            logger.info(f"✅ yt-dlp: прямая ссылка получена: {direct_url[:80]}...")
        else:
            logger.warning("⚠️  yt-dlp: не удалось извлечь прямую ссылку.")
        return direct_url
    except Exception as e:
        logger.error(f"❌ yt-dlp exception: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# СТРАТЕГИЯ 3: Прямой CDN URL документа (для attachment.type == "doc")
# Работает только пока URL «горячий» (~1 час после получения сообщения)
# ─────────────────────────────────────────────────────────────────
async def _verify_doc_url(doc_url: str) -> Optional[str]:
    """
    Проверяет, что doc URL возвращает реальные байты видеофайла, а не HTML-редирект.
    Если проверка прошла — возвращает тот же URL (годится для передачи в Kling API).
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": "https://vk.com/",
            "Accept": "video/webm,video/ogg,video/*;q=0.9,*/*;q=0.5",
        }
        async with aiohttp.ClientSession(connector=get_connector()) as session:
            async with session.head(
                doc_url,
                headers=headers,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"⚠️  Doc URL HEAD status={resp.status}")
                    return None
                ct = resp.headers.get("Content-Type", "").lower()
                if "text/html" in ct:
                    logger.warning(f"⚠️  Doc URL вернул HTML — CDN ссылка протухла.")
                    return None
                cl = int(resp.headers.get("Content-Length", 0))
                if cl < 10_000:
                    logger.warning(f"⚠️  Doc URL Content-Length слишком мал: {cl}")
                    return None
                logger.info(f"✅ Doc URL валиден (ct={ct}, size={cl} bytes): {doc_url[:80]}...")
                return doc_url
    except Exception as e:
        logger.error(f"❌ Doc URL проверка упала: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ: каскад из трёх стратегий
# ─────────────────────────────────────────────────────────────────
async def resolve_vk_video_direct_url(
    *,
    # Для видео (attachment.type == "video")
    owner_id: Optional[int] = None,
    video_id: Optional[int] = None,
    access_key: Optional[str] = None,
    # Для документов (attachment.type == "doc")
    doc_url: Optional[str] = None,
) -> Optional[str]:
    """
    Возвращает прямую .mp4 ссылку для передачи в Kling Motion API.

    Порядок попыток:
      1. VK API video.get → files (только для видео-вложений, нужен user_token)
      2. yt-dlp по canonical URL ВКонтакте (универсально, даже для чужих видео)
      3. Прямой doc.url — если это был документ и URL ещё не протух

    Использование из handlers.py:
        # Для attachment.type == "video":
        url = await resolve_vk_video_direct_url(
            owner_id=attachment.video.owner_id,
            video_id=attachment.video.id,
            access_key=getattr(attachment.video, "access_key", None),
        )

        # Для attachment.type == "doc" (mp4/mov):
        url = await resolve_vk_video_direct_url(doc_url=attachment.doc.url)
    """
    # --- Стратегия 1: VK API (только для video-вложений) ---
    if owner_id and video_id:
        url = await _resolve_via_vk_api(owner_id, video_id, access_key)
        if url:
            return url

        # Строим canonical URL для yt-dlp
        canonical = f"https://vk.com/video{owner_id}_{video_id}"
        if access_key:
            canonical += f"?access_key={access_key}"
    else:
        canonical = None

    # --- Стратегия 2: yt-dlp ---
    ytdlp_url = canonical or doc_url  # для документов используем сам URL
    if ytdlp_url:
        url = await _resolve_via_ytdlp(ytdlp_url)
        if url:
            return url

    # --- Стратегия 3: Прямой doc URL (fallback для документов) ---
    if doc_url:
        url = await _verify_doc_url(doc_url)
        if url:
            return url

    logger.error("❌ Все стратегии resolve_vk_video_direct_url исчерпаны.")
    return None
