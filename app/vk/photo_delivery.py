"""
Доставка фото клиенту в VK с защитой от потерь.

Возможности:
- Кэш байтов результата на диск (по hash(user_id+model+prompt+urls))
- Retry на upload в VK (3 попытки, экспоненциальный backoff)
- Fallback: если VK Upload не работает — отправляем ссылку на Catbox
- Дедупликация: если такой же запрос недавно (≤10 мин) выполнялся успешно —
  переотправляем из кэша, не дёргая Polza.

Экспортируемые функции:
- request_hash(user_id, model, prompt, photo_urls)
- cache_lookup_result(req_hash) -> (bytes, ext) | None
- cache_store_result(req_hash, img_bytes, ext)
- deliver_photo(bot, user_id, img_bytes, ext, caption, keyboard, req_hash=None) -> bool
- deliver_multi_photos(bot, user_id, images, ext, caption, keyboard, req_hash=None) -> bool

Пользователю всегда возвращается логичный ответ; если не доставлено вообще —
функция возвращает False, и вызывающий код НЕ должен делать charge.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import List, Optional, Tuple

from vkbottle import PhotoMessageUploader

from app.network import upload_file_smart

logger = logging.getLogger(__name__)

# === Конфиг ===
CACHE_DIR = Path(os.environ.get("VKBOT_PHOTO_CACHE_DIR", "/var/lib/vkbot_photo_cache"))
CACHE_TTL_SECONDS = 60 * 60          # держим файлы 1 час, потом чистим
DEDUP_TTL_SECONDS = 10 * 60          # 10 минут: окно дедупликации одинаковых запросов
UPLOAD_MAX_ATTEMPTS = 3
UPLOAD_BACKOFF_BASE = 1.5            # 1.5, 3.0, 4.5 сек
SEND_MAX_ATTEMPTS = 3
SEND_BACKOFF_BASE = 1.0              # 1, 2, 4 сек

# Создаём директорию кэша при импорте
try:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    logger.warning(f"Cannot create cache dir {CACHE_DIR}: {e}")


# === Хэш запроса ===

def request_hash(user_id: int, model: str, prompt: str, photo_urls: List[str] | None) -> str:
    """Стабильный хеш для дедупликации одинаковых запросов."""
    urls_norm = ",".join(sorted(photo_urls)) if photo_urls else ""
    raw = f"{user_id}|{model}|{(prompt or '').strip()}|{urls_norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# === Кэш на диске ===

def _meta_path(req_hash: str) -> Path:
    return CACHE_DIR / f"{req_hash}.json"


def cache_store_result(req_hash: str, img_bytes_list: List[bytes], ext: str) -> None:
    """Сохраняем результат(ы) генерации на диск."""
    if not req_hash or not img_bytes_list:
        return
    try:
        ext = (ext or "jpg").lower().lstrip(".")
        if ext == "jpeg":
            ext = "jpg"
        files: List[str] = []
        for idx, blob in enumerate(img_bytes_list):
            if not blob:
                continue
            blob_path = CACHE_DIR / f"{req_hash}_{idx}.{ext}"
            blob_path.write_bytes(blob)
            files.append(blob_path.name)
        meta = {
            "ext": ext,
            "files": files,
            "ts": int(time.time()),
            "count": len(files),
        }
        _meta_path(req_hash).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(f"📦 Cached result {req_hash} ({len(files)} file(s), ext={ext})")
    except Exception as e:
        logger.warning(f"cache_store_result failed for {req_hash}: {e}")


def cache_lookup_result(req_hash: str) -> Optional[Tuple[List[bytes], str]]:
    """Возвращает (list[bytes], ext), если есть свежий кэш (<DEDUP_TTL)."""
    if not req_hash:
        return None
    meta_p = _meta_path(req_hash)
    if not meta_p.exists():
        return None
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        age = int(time.time()) - int(meta.get("ts", 0))
        if age > DEDUP_TTL_SECONDS:
            return None
        ext = meta.get("ext", "jpg")
        files = meta.get("files") or []
        blobs: List[bytes] = []
        for fn in files:
            p = CACHE_DIR / fn
            if p.exists():
                blobs.append(p.read_bytes())
        if not blobs:
            return None
        return blobs, ext
    except Exception as e:
        logger.warning(f"cache_lookup_result failed for {req_hash}: {e}")
        return None


def cache_cleanup_expired() -> int:
    """Удалить все файлы старше CACHE_TTL_SECONDS. Возвращает кол-во удалённых."""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    cutoff = time.time() - CACHE_TTL_SECONDS
    try:
        for f in CACHE_DIR.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"cache_cleanup_expired error: {e}")
    return removed


# === Retry-обёртки ===

async def _upload_one_to_vk(api, img_bytes: bytes, peer_id: int, ext: str, idx: int = 0) -> Optional[str]:
    """Upload одного фото в VK с retry. Возвращает attachment-строку или None."""
    import tempfile
    import os
    
    last_err: Optional[Exception] = None
    
    fd, path = tempfile.mkstemp(suffix=f".{ext}")
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(img_bytes)
            
        for attempt in range(1, UPLOAD_MAX_ATTEMPTS + 1):
            try:
                uploader = PhotoMessageUploader(api)
                attachment = await uploader.upload(file_source=path, peer_id=peer_id)
                if attempt > 1:
                    logger.info(f"🔁 VK upload OK on attempt {attempt} (peer={peer_id})")
                return attachment
            except Exception as e:
                last_err = e
                wait = UPLOAD_BACKOFF_BASE * attempt
                logger.warning(
                    f"⚠️ VK upload failed attempt {attempt}/{UPLOAD_MAX_ATTEMPTS} "
                    f"(peer={peer_id}, idx={idx}): {type(e).__name__}: {e}. "
                    f"Sleep {wait:.1f}s"
                )
                if attempt < UPLOAD_MAX_ATTEMPTS:
                    await asyncio.sleep(wait)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
            
    logger.error(
        f"❌ VK upload exhausted {UPLOAD_MAX_ATTEMPTS} attempts "
        f"for peer={peer_id} idx={idx}: {last_err}"
    )
    return None


async def _send_message_with_retry(api, **kwargs) -> bool:
    """Послать messages.send с retry."""
    last_err: Optional[Exception] = None
    for attempt in range(1, SEND_MAX_ATTEMPTS + 1):
        try:
            await api.messages.send(**kwargs)
            if attempt > 1:
                logger.info(f"🔁 messages.send OK on attempt {attempt}")
            return True
        except Exception as e:
            last_err = e
            wait = SEND_BACKOFF_BASE * (2 ** (attempt - 1))
            logger.warning(
                f"⚠️ messages.send failed attempt {attempt}/{SEND_MAX_ATTEMPTS}: "
                f"{type(e).__name__}: {e}. Sleep {wait:.1f}s"
            )
            if attempt < SEND_MAX_ATTEMPTS:
                await asyncio.sleep(wait)
    logger.error(f"❌ messages.send exhausted: {last_err}")
    return False


# === Доставка ===

async def deliver_multi_photos(
    bot,
    user_id: int,
    images: List[bytes],
    ext: str,
    caption: str,
    keyboard=None,
    req_hash: Optional[str] = None,
) -> bool:
    """Доставить >=1 фото клиенту с retry и fallback на ссылки.

    Возвращает True если хотя бы основной результат доставлен (фото или ссылка).
    Кэширует байты в файл, чтобы фоновая задача могла переотправить.
    """
    if not images:
        return False

    ext = (ext or "jpg").lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    if ext not in ("jpg", "png", "webp"):
        ext = "jpg"

    # 1. Сохраняем результат в кэш (чтобы при провале фоновый таск мог дослать)
    if req_hash:
        cache_store_result(req_hash, images, ext)

    # 2. Пробуем upload каждой картинки с retry
    attachments: List[str] = []
    for idx, img_bytes in enumerate(images):
        if not img_bytes or len(img_bytes) < 64:
            logger.warning(f"deliver: skipping empty image idx={idx} for user={user_id}")
            continue
        att = await _upload_one_to_vk(bot.api, img_bytes, peer_id=user_id, ext=ext, idx=idx)
        if att:
            attachments.append(att)

    # 3. Если хотя бы одна картинка загрузилась — отправляем как вложение
    if attachments:
        ok = await _send_message_with_retry(
            bot.api,
            user_id=user_id,
            message=caption + (f"\n\n📷 Фото: {len(attachments)} шт." if len(attachments) > 1 else ""),
            attachment=",".join(attachments),
            keyboard=keyboard,
            random_id=0,
        )
        if ok:
            return True
        # send упал даже после retry — пробуем дальше через ссылки

    # 4. Fallback: грузим в Catbox и шлём ссылками
    logger.warning(f"⚠️ VK upload недоступен для user={user_id}, пробуем Catbox-fallback")
    urls: List[str] = []
    for idx, img_bytes in enumerate(images):
        if not img_bytes or len(img_bytes) < 64:
            continue
        try:
            url = await upload_file_smart(img_bytes, filename=f"result_{idx}.{ext}")
            if url:
                urls.append(url)
        except Exception as e:
            logger.error(f"Catbox upload failed idx={idx}: {e}")

    if urls:
        urls_text = "\n".join(urls)
        msg = (
            f"{caption}\n\n"
            f"⚠️ ВКонтакте временно не принимает вложения. "
            f"Скачать фото можно по ссылк{'е' if len(urls) == 1 else 'ам'} ниже "
            f"(действительна несколько часов):\n\n"
            f"{urls_text}"
        )
        ok = await _send_message_with_retry(
            bot.api,
            user_id=user_id,
            message=msg,
            keyboard=keyboard,
            random_id=0,
        )
        if ok:
            return True

    # 5. Совсем ничего не сработало — известим клиента и оставим в кэше для retry-таска
    logger.error(f"❌ Полная неудача доставки для user={user_id}, req_hash={req_hash}")
    await _send_message_with_retry(
        bot.api,
        user_id=user_id,
        message=(
            "⚠️ Произошла ошибка при отправке результата. "
            "Мы получили ваше изображение и автоматически попробуем доставить его повторно "
            "в течение нескольких минут.\n\n"
            "Если через 5 минут результат не придёт — напишите в поддержку."
        ),
        keyboard=keyboard,
        random_id=0,
    )
    return False


async def deliver_photo(
    bot,
    user_id: int,
    img_bytes: bytes,
    ext: str,
    caption: str,
    keyboard=None,
    req_hash: Optional[str] = None,
) -> bool:
    """Удобная обёртка для одного фото."""
    return await deliver_multi_photos(
        bot, user_id, [img_bytes], ext, caption, keyboard, req_hash
    )


# === Фоновая задача переотправки ===

async def schedule_redelivery(
    bot,
    user_id: int,
    req_hash: str,
    caption: str,
    keyboard=None,
    delay_seconds: int = 60,
    max_retries: int = 3,
):
    """Запустить фоновую задачу переотправки из кэша.

    Используется, когда deliver_multi_photos вернул False:
    мы говорим клиенту "попробуем ещё раз", а через delay_seconds в фоне
    повторно пытаемся доставить тот же результат.
    """
    for attempt in range(1, max_retries + 1):
        await asyncio.sleep(delay_seconds * attempt)  # 60s, 120s, 180s
        cached = cache_lookup_result(req_hash)
        if not cached:
            logger.info(f"🗑 redelivery: cache miss for {req_hash}, stop")
            return
        images, ext = cached
        logger.info(
            f"🔁 redelivery attempt {attempt}/{max_retries} for user={user_id} req_hash={req_hash}"
        )
        ok = await deliver_multi_photos(
            bot, user_id, images, ext, caption, keyboard, req_hash=None  # уже в кэше
        )
        if ok:
            logger.info(f"✅ redelivery succeeded for user={user_id}")
            return
    logger.error(f"❌ redelivery exhausted for user={user_id} req_hash={req_hash}")
