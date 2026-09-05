"""VK Message Handlers - Complete implementation mirroring Telegram"""
import logging
import asyncio
import traceback
import json
import aiohttp
from typing import Optional, List
from vkbottle.bot import Bot, Message
from vkbottle import PhotoMessageUploader, VideoUploader, GroupEventType, GroupTypes, ShowSnackbarEvent

from app.vk.keyboards import (
    get_main_keyboard,
    get_model_keyboard,
    get_video_model_keyboard,
    get_cancel_keyboard,
    get_admin_keyboard,
    get_photo_collection_keyboard,
    VK_REFERRAL_MENU_BUTTON,
    VK_REFERRAL_WITHDRAW_BUTTON,
    VK_REFERRAL_BACK_BUTTON,
    get_referral_section_keyboard,
    get_admin_withdraw_complete_keyboard,
)
from app.vk.state_manager import VKStateManager
from app.vk.file_handler import download_vk_photo, download_vk_video, bytes_to_base64_data_uri
from app.network import get_connector, timeout_config
from app.vk.models.video.kling_motion import _download_vk_doc_video
from app.vk.generation import (
    has_balance, charge, generate_photo as generate, generate_video, COSTS
)
from app.vk.photo_delivery import (
    request_hash,
    cache_lookup_result,
    deliver_multi_photos,
    schedule_redelivery,
    cache_cleanup_expired,
)
from app.services.telegram_file import get_telegram_photo_url, download_telegram_file
import vk_database as db
from app.config import settings

logger = logging.getLogger(__name__)

# Минимальная сумма вывода с реферального счёта (руб.)
MIN_REFERRAL_WITHDRAW = 100

MODEL_NAMES = {
    "nanabanana": "🍌 NanoBanana",
    "nanabanana_2": "🍌 NanoBanana 2",
    "nanabanana_pro": "💎 NanoBanana PRO",
    "seedream": "🌊 SeeDream 5.0 Lite",
    "seedream_pro": "🌊 SeeDream 5.0 Pro",
    "grok_imagine": "🤖 Grok",
    "gpt5_image": "🧠 GPT-5",
    "flux2_pro": "⚡ Flux-2 Pro",
    "flux2_flex": "⚡ Flux-2 Flex",
    "qwen_image2": "🔮 Qwen Image 2",
    "kling_motion_720": "🎬 Motion 720p",
    "kling_motion_1080": "🎬 Motion 1080p",
}

active_tasks = set()


async def _build_image_sources(
    file_urls: List[str],
    force_data_uri: bool = False,
) -> List[str]:
    """Build image sources for generation API"""
    sources: List[str] = []

    for file_url in file_urls:
        if not force_data_uri:
            sources.append(file_url)
            continue

        file_bytes, mime = await download_vk_photo(file_url)
        if file_bytes and mime and mime.startswith("image/"):
            sources.append(bytes_to_base64_data_uri(file_bytes, mime))

    first_type = "none"
    if sources:
        first_type = "data_uri" if sources[0].startswith("data:") else "url"

    logger.info(f"VK photo sources prepared: count={len(sources)} first_type={first_type}")
    return sources


async def background_photo_gen(
    bot: Bot,
    user_id: int,
    photo_urls: List[str],
    prompt: str,
    model: str,
    aspect_ratio: str = "1:1",
    quality: str = "1K",
):
    """Background photo generation task.

    Защита от потерь фото и двойных трат на Polza:
    1) Перед генерацией проверяем дисковый кэш (10-минутное окно дедупликации).
    2) Сразу после успешной генерации сохраняем байты в кэш.
    3) Upload в VK с 3 ретраями + fallback на Catbox-ссылку.
    4) charge только после успешной доставки клиенту.
    5) Если совсем не доставили — фоновая задача переотправки.
    """
    try:
        # Периодически чистим устаревшие файлы кэша (без блокировки)
        try:
            cache_cleanup_expired()
        except Exception:
            pass

        # Стабильный хеш запроса для дедупликации и кэша
        try:
            req_hash = request_hash(user_id, model, prompt, photo_urls)
        except Exception:
            req_hash = None

        caption_ok = f"✨ Ваше изображение готово! ({MODEL_NAMES.get(model)})"

        # 1) Проверяем кэш — если такой же запрос недавно генерировался,
        # переотправляем без обращения к Polza.
        if req_hash:
            cached = cache_lookup_result(req_hash)
            if cached:
                cached_imgs, cached_ext = cached
                logger.info(
                    f"♻️ Reusing cached result for user={user_id} req_hash={req_hash} "
                    f"({len(cached_imgs)} img, ext={cached_ext})"
                )
                ok = await deliver_multi_photos(
                    bot, user_id, cached_imgs, cached_ext,
                    caption=caption_ok,
                    keyboard=get_main_keyboard(user_id),
                    req_hash=req_hash,
                )
                if ok:
                    # ВНИМАНИЕ: не делаем charge повторно — мы уже списали при первом успехе.
                    logger.info(f"✅ Photo redelivered from cache for VK user {user_id}")
                else:
                    asyncio.create_task(schedule_redelivery(
                        bot, user_id, req_hash,
                        caption=caption_ok,
                        keyboard=get_main_keyboard(user_id),
                    ))
                return

        # 2) Подготавливаем источники изображений
        photo_sources = await _build_image_sources(photo_urls, force_data_uri=False)

        if model in ("nanabanana_pro", "seedream", "seedream_pro", "flux2_pro", "flux2_flex", "qwen_image2"):
            photo_sources = [
                s for s in photo_sources
                if isinstance(s, str) and (s.startswith("http://") or s.startswith("https://"))
            ]
            logger.info(f"{model} filtered url_sources={len(photo_sources)}")

        if not photo_sources:
            await bot.api.messages.send(
                user_id=user_id,
                message="⚠️ Не удалось подготовить фото-референс.",
                keyboard=get_main_keyboard(user_id),
                random_id=0
            )
            return

        # 3) Генерация в Polza
        result = await generate(
            image_urls=photo_sources, prompt=prompt, model=model,
            aspect_ratio=aspect_ratio, quality=quality
        )

        if not result or not result[0]:
            await bot.api.messages.send(
                user_id=user_id,
                message="⚠️ Не удалось получить результат от нейросети.",
                keyboard=get_main_keyboard(user_id),
                random_id=0
            )
            return

        img_bytes, ext, _ = result

        # 4) Нормализуем результат к списку байтов
        if isinstance(img_bytes, list):
            images = [b for b in img_bytes if b and len(b) >= 64]
        elif isinstance(img_bytes, (bytes, bytearray)):
            images = [bytes(img_bytes)] if len(img_bytes) >= 64 else []
        else:
            images = []

        if not images:
            await bot.api.messages.send(
                user_id=user_id,
                message="⚠️ Пустой файл изображения от нейросети.",
                keyboard=get_main_keyboard(user_id),
                random_id=0,
            )
            return

        # 5) Доставка клиенту с retry и fallback
        caption = (
            f"✨ Ваши изображения готовы! ({MODEL_NAMES.get(model)}) - {len(images)} шт."
            if len(images) > 1 else caption_ok
        )

        ok = await deliver_multi_photos(
            bot, user_id, images, ext or "jpg",
            caption=caption,
            keyboard=get_main_keyboard(user_id),
            req_hash=req_hash,
        )

        if ok:
            # 6) Списываем монеты только при успешной доставке
            await charge(user_id, model)
            logger.info(f"✅ Photo delivered for VK user {user_id} ({len(images)} img)")
        else:
            # Поставлен фоновый retry — клиент уже уведомлён внутри deliver
            logger.warning(
                f"⚠️ Photo delivery failed for VK user {user_id}, scheduling redelivery "
                f"(req_hash={req_hash})"
            )
            if req_hash:
                asyncio.create_task(schedule_redelivery(
                    bot, user_id, req_hash,
                    caption=caption,
                    keyboard=get_main_keyboard(user_id),
                ))

    except Exception as e:
        logger.error(f"❌ Photo generation error: {traceback.format_exc()}")
        try:
            await bot.api.messages.send(
                user_id=user_id,
                message="⚠️ Ошибка при создании фото.",
                keyboard=get_main_keyboard(user_id),
                random_id=0
            )
        except Exception:
            pass


def get_mp4_duration(data: bytes) -> int:
    try:
        idx = data.find(b'mvhd')
        if idx == -1: return 5
        version = data[idx+4]
        if version == 0:
            timescale = int.from_bytes(data[idx+12:idx+16], 'big')
            duration = int.from_bytes(data[idx+16:idx+20], 'big')
        else:
            timescale = int.from_bytes(data[idx+20:idx+24], 'big')
            duration = int.from_bytes(data[idx+24:idx+32], 'big')
        if timescale > 0: return round(duration / timescale)
    except Exception:
        pass
    return 5

async def background_video_gen(
    bot: Bot,
    user_id: int,
    photo_url: str,
    prompt: str,
    model: str,
    motion_video_url: Optional[str] = None,
    motion_doc_ref: Optional[str] = None,
):
    """Background video generation task"""
    try:
        final_prompt = prompt if (prompt and prompt.strip() != ".") else "High quality, cinematic"
        
        # Если есть doc_ref, получаем свежую прямую ссылку через VK API
        if motion_doc_ref and motion_video_url:
            try:
                docs_info = await bot.api.docs.get_by_id(docs=[motion_doc_ref])
                if docs_info and len(docs_info) > 0:
                    fresh_url = docs_info[0].url
                    if fresh_url:
                        logger.info(f"📎 VK API fresh doc URL: {fresh_url}")
                        motion_video_url = fresh_url
                    else:
                        logger.warning("⚠️ VK API returned doc without URL, using original")
                else:
                    logger.warning("⚠️ VK API docs.getById returned empty, using original URL")
            except Exception as e:
                logger.error(f"⚠️ VK API docs.getById failed: {e}, using original URL")

        result = await generate_video(photo_url, final_prompt, model, motion_video_url=motion_video_url)

        if result and result[0]:
            video_bytes, ext, _ = result
            
            # Определяем точную длительность и стоимость
            duration = get_mp4_duration(video_bytes)
            per_sec_cost = 14 if model == "kling_motion_720" else 20
            total_cost = duration * per_sec_cost

            # Upload video to VK
            video_uploader = VideoUploader(bot.api)
            attachment = await video_uploader.upload(
                file_source=video_bytes,
                name=f"video_{user_id}.{ext}",
                description="Сгенерировано нейросетью"
            )

            await bot.api.messages.send(
                user_id=user_id,
                message=f"✅ Ваше видео готово! ({MODEL_NAMES.get(model)})\n\n⏳ Длительность: {duration} сек.\n💰 С баланса списано: {total_cost} руб.",
                attachment=attachment,
                keyboard=get_main_keyboard(user_id),
                random_id=0
            )
            # Списываем посчитанную сумму
            await charge(user_id, total_cost)
            logger.info(f"✅ Video generated for VK user {user_id}. Duration: {duration}s, Cost: {total_cost}")
        else:
            await bot.api.messages.send(
                user_id=user_id,
                message="⚠️ Не удалось сгенерировать видео. Баланс сохранен.",
                keyboard=get_main_keyboard(user_id),
                random_id=0
            )

    except Exception as e:
        logger.error(f"❌ Video generation error: {traceback.format_exc()}")
        await bot.api.messages.send(
            user_id=user_id,
            message="⚠️ Произошла ошибка в процессе генерации видео.",
            keyboard=get_main_keyboard(user_id),
            random_id=0
        )


class VKHandlers:
    """VK Bot Handlers"""

    def __init__(self, bot: Bot, state_manager: VKStateManager):
        self.bot = bot
        self.state = state_manager

        # Register handlers
        self.bot.on.message()(self.on_message)
        self.bot.on.raw_event(GroupEventType.MESSAGE_EVENT, dataclass=GroupTypes.MessageEvent)(
            self.on_message_event
        )

    @staticmethod
    def _is_start_command(message: Message, normalized_text: str) -> bool:
        """Detect /start in plain text, mention form, args form, and payload."""
        command = normalized_text.split(maxsplit=1)[0] if normalized_text else ""

        # Examples: /start, /start ref123, /start@club12345
        if command == "/start" or command.startswith("/start@"):
            return True

        if normalized_text in {"start", "привет", "начать"}:
            return True

        payload = getattr(message, "payload", None)
        if payload:
            try:
                payload_obj = json.loads(payload) if isinstance(payload, str) else payload
                payload_command = str(payload_obj.get("command", "")).strip().lower()
                payload_action = str(payload_obj.get("action", "")).strip().lower()
                if payload_command == "start" or payload_action == "start":
                    return True
            except Exception:
                pass

        return False

    async def on_message(self, message: Message) -> str:
        """Main message handler"""
        user_id = message.from_id
        text = (message.text or "").strip().lower()
        is_admin = user_id in settings.vk_admin_ids

        logger.info(f"VK Message from {user_id}: {text}")

        # Get current state
        state = await self.state.get_state(user_id)
        user_data = await self.state.get_data(user_id)

        # --- CANCEL/BACK ---
        if text in (
            "отменить",
            "назад",
            "❌ отменить",
            "🔙 назад",
            "отмена",
            "❌",
            "🔙",
            VK_REFERRAL_BACK_BUTTON.lower(),
        ):
            await self.state.clear_state(user_id)
            await self.state.clear_data(user_id)
            await message.answer(
                "🔙 Вы вернулись в главное меню.",
                keyboard=get_main_keyboard(user_id)
            )
            return

        # --- ADMIN PANEL ---
        elif is_admin and text in ("🛡", "админ", "🛡 админ панель"):
            return await self.handle_admin_panel(message)
        
        elif is_admin and text in ("👥 пользователи", "пользователи"):
            return await self.handle_admin_stats(message)

        elif is_admin and text in ("💳 выдать баланс", "выдать баланс"):
            await self.state.set_state(user_id, "admin_waiting_grant")
            await message.answer(
                "📝 Введите данные в формате:\n\nID:Сумма\nНапример: 424721069:100",
                keyboard=get_cancel_keyboard()
            )
            return

        elif is_admin and state == "admin_waiting_grant":
            return await self.handle_admin_grant(message)

        # --- START / MAIN MENU ---
        elif self._is_start_command(message, text):
            return await self.handle_start(message)

        # --- STATE-BASED HANDLERS ---
        elif state == "waiting_for_model":
            return await self.handle_model_choice(message, user_data)

        elif state == "waiting_for_photo":
            return await self.handle_photo_upload(message, user_data)

        elif state == "collecting_photos":
            return await self.handle_photo_collection(message, user_data)

        elif state == "waiting_for_aspect_ratio":
            return await self.handle_aspect_ratio(message, user_data)

        elif state == "waiting_for_quality":
            return await self.handle_quality(message, user_data)

        elif state == "waiting_for_motion_video":
            return await self.handle_motion_video_upload(message, user_data)

        elif state == "waiting_for_prompt":
            return await self.handle_prompt(message, user_data)
            
        elif state == "waiting_for_deposit_amount":
            return await self.handle_deposit_amount(message, user_data)

        elif state == "waiting_referral_withdraw_amount":
            return await self.handle_referral_withdraw_amount(message, user_data)

        elif state == "waiting_referral_withdraw_method":
            return await self.handle_referral_withdraw_method(message, user_data)

        elif state == "waiting_referral_withdraw_details":
            return await self.handle_referral_withdraw_details(message, user_data)

        # --- PHOTO SESSION ---
        elif text in ("начать фотосессию", "📸 начать фотосессию"):
            return await self.handle_start_photo(message)

        # --- VIDEO SESSION ---
        elif text in ("оживить фото", "🎬 оживить фото"):
            return await self.handle_start_video(message)

        # --- BALANCE ---
        elif text in ("мой баланс", "💰 мой баланс", "баланс", "💰"):
            return await self.handle_balance(message)

        # --- DEPOSIT ---
        elif text in ("пополнить", "💳 пополнить", "💳"):
            return await self.handle_deposit(message)

        # --- HELP ---
        elif text in ("помощь", "🆘 помощь", "🆘"):
            return await self.handle_help(message)

        elif text == VK_REFERRAL_MENU_BUTTON.lower():
            return await self.handle_referral_menu(message)

        elif text == VK_REFERRAL_WITHDRAW_BUTTON.lower():
            return await self.handle_referral_withdraw_start(message)

        else:
            await message.answer(
                "👋 Добро пожаловать! Выберите действие:",
                keyboard=get_main_keyboard(user_id)
            )
            return

    async def handle_start(self, message: Message) -> str:
        """Handle /start command with referral support"""
        user_id = message.from_id
        is_admin = user_id in settings.vk_admin_ids
        text = (message.text or "").strip().lower()

        logger.info(f"🚀 VK /start from user {user_id}")

        # --- Referral Logic ---
        referrer_id = None

        # 0. Главный источник — VK ref-параметр из ссылки vk.com/write-{group_id}?ref=user_12345
        # Это поле приходит ТОЛЬКО при первом обращении пользователя к сообществу по такой ссылке.
        ref_param = getattr(message, "ref", None)
        ref_source = getattr(message, "ref_source", None)
        if ref_param:
            raw = str(ref_param).strip()
            # Поддерживаем форматы: "12345", "user_12345", "ref12345"
            if raw.lower().startswith("user_"):
                raw = raw[5:]
            elif raw.lower().startswith("ref"):
                raw = raw[3:]
            if raw.isdigit():
                referrer_id = int(raw)
                logger.info(
                    f"🔗 Реферал из VK ref-ссылки: referrer={referrer_id}, "
                    f"source={ref_source}, user={user_id}"
                )

        # 1. Fallback: текстовая команда /start 12345 или /start ref12345
        if not referrer_id:
            parts = text.split()
            if len(parts) > 1:
                ref_part = parts[1].replace("ref", "")
                if ref_part.isdigit():
                    referrer_id = int(ref_part)
                    logger.info(f"🔗 Реферал из текста /start: referrer={referrer_id}, user={user_id}")

        # 2. Fallback: payload (VK Mini Apps / кнопки с ref)
        payload = getattr(message, "payload", None)
        if payload and not referrer_id:
            try:
                payload_obj = json.loads(payload) if isinstance(payload, str) else payload
                ref_from_payload = payload_obj.get("ref") or payload_obj.get("referrer")
                if str(ref_from_payload).isdigit():
                    referrer_id = int(ref_from_payload)
                    logger.info(f"🔗 Реферал из payload: referrer={referrer_id}, user={user_id}")
            except: pass

        # Защита от self-referral
        if referrer_id == user_id:
            referrer_id = None

        # Register or update in database
        try:
            await db.create_new_user(user_id, referrer_id=referrer_id)
            if referrer_id and referrer_id != user_id:
                await db.set_referrer(user_id, referrer_id)
            
            balance = await db.get_balance(user_id)
        except Exception as e:
            logger.error(f"❌ DB error for VK user {user_id}: {e}")
            balance = "error"

        welcome_text = (
            "🌟 Привет! Я твой персональный AI-фотограф.\n\n"
            "Превращаю обычные селфи в профессиональные шедевры за считанные секунды. 📸\n\n"
            "🎁 Поздравляю! Тебе начислен приветственный бонус — 17 руб. "
            "Этого хватит на твою первую генерацию!\n\n"
            f"💰 Мой баланс: {balance} руб.\n\n"
            "Выбери действие в меню ниже и давай начнем! 👇"
        )

        kb = get_main_keyboard(user_id)
        if is_admin:
            welcome_text += "\n\n🛡 У тебя есть доступ к админ-панели."

        await message.answer(welcome_text, keyboard=kb)
        await self.state.clear_state(user_id)
        return

    # =====================================
    # ADMIN HANDLERS
    # =====================================

    async def handle_admin_panel(self, message: Message) -> str:
        """Show admin panel"""
        await message.answer(
            "🛡 Панель администратора\nВыбери действие:",
            keyboard=get_admin_keyboard()
        )
        return

    async def handle_admin_stats(self, message: Message) -> str:
        """Show user count stats"""
        try:
            count = await db.get_users_count()
            await message.answer(
                f"📊 Статистика бота\n\n"
                f"👥 Всего пользователей: {count}",
                keyboard=get_admin_keyboard()
            )
        except Exception as e:
            logger.error(f"❌ Admin stats error: {e}")
            await message.answer("❌ Ошибка получения статистики.", keyboard=get_admin_keyboard())
        return

    async def handle_admin_grant(self, message: Message) -> str:
        """Grant balance to user by ID"""
        user_id = message.from_id
        raw = (message.text or "").strip()

        try:
            parts = raw.split(":")
            if len(parts) != 2:
                raise ValueError
            target_id = int(parts[0].strip())
            amount = int(parts[1].strip())
            if amount <= 0:
                raise ValueError
        except (ValueError, IndexError):
            await message.answer(
                "❌ Неправильный формат.\nВведите в формате: ID:Сумма\nНапример: 424721069:100",
                keyboard=get_cancel_keyboard()
            )
            return

        success = await db.update_balance(target_id, amount)
        await self.state.clear_state(user_id)

        if success:
            new_balance = await db.get_balance(target_id)
            await message.answer(
                f"✅ Готово! Пользователю {target_id} начислено +{amount} руб.\n"
                f"💰 Текущий баланс: {new_balance} руб.",
                keyboard=get_admin_keyboard()
            )
        else:
            await message.answer(
                "❌ Не удалось начислить баланс. Проверьте ID пользователя.",
                keyboard=get_admin_keyboard()
            )
        return
    async def handle_start_photo(self, message: Message) -> str:
        """Start photo generation flow"""
        user_id = message.from_id

        model_text = "🎨 Выбери модель для обработки фото:"
        await message.answer(model_text, keyboard=get_model_keyboard())
        await self.state.set_state(user_id, "waiting_for_model")
        await self.state.set_data(user_id, {"session_type": "photo"})
        return

    async def handle_start_video(self, message: Message) -> str:
        """Start video generation flow"""
        user_id = message.from_id

        video_text = "🎬 Выбери качество для оживления фото (Kling Motion):"
        await message.answer(video_text, keyboard=get_video_model_keyboard())
        await self.state.set_state(user_id, "waiting_for_model")
        await self.state.set_data(user_id, {"session_type": "video"})
        return

    async def handle_model_choice(self, message: Message, user_data: dict) -> str:
        """Handle model selection"""
        user_id = message.from_id
        text = (message.text or "").strip().lower()
        session_type = user_data.get("session_type", "photo")

        # Parse model from text (совпадает с кнопками из keyboards.py)
        model = None
        if "pro" in text and "nanabanana" in text:
            model = "nanabanana_pro"
        elif "pro" in text and "💎" in text:
            model = "nanabanana_pro"
        elif "2" in text and "nanabanana" in text:
            model = "nanabanana_2"
        elif "nanabanana" in text or ("🍌" in text and "pro" not in text and "2" not in text):
            model = "nanabanana"
        elif "🍌" in text and "2" in text:
            model = "nanabanana_2"
        elif "🍌" in text and "pro" in text:
            model = "nanabanana_pro"
        elif "💎" in text:
            model = "nanabanana_pro"
        elif ("seedream" in text or "🌊" in text) and "pro" in text:
            model = "seedream_pro"
        elif "seedream" in text or "🌊" in text or "5.0" in text or "lite" in text:
            model = "seedream"
        elif "grok" in text or "🤖" in text:
            model = "grok_imagine"
        elif "gpt-5" in text or "gpt5" in text or "🧠" in text:
            model = "gpt5_image"
        elif "flux" in text and "flex" in text:
            model = "flux2_flex"
        elif "flux" in text or "⚡" in text:
            model = "flux2_pro"
        elif "qwen" in text or "🔮" in text:
            model = "qwen_image2"
        elif "720" in text:
            model = "kling_motion_720"
        elif "1080" in text:
            model = "kling_motion_1080"
        elif "motion" in text or "🎭" in text:
            model = "kling_motion_720" # fallback

        if not model:
            await message.answer("❌ Модель не распознана. Попробуй еще раз.")
            return

        # Check balance and generate insufficient funds payment link
        cost = COSTS.get(model, 0)
        current_bal = await db.get_balance(user_id)
        
        if current_bal < cost:
            missing_amount = cost - current_bal
            from app.config import settings
            from urllib.parse import urlencode
            from app.vk.keyboards import get_payment_keyboard
            
            params = {
                "do": "pay",
                "order_id": f"{user_id}_{missing_amount}",
                "products[0][name]": "Генерация с помощью нейросети",
                "products[0][price]": missing_amount,
                "products[0][quantity]": 1
            }
            payment_url = f"{settings.vk_prodamus_url}/?{urlencode(params, encoding='windows-1251')}"
            
            await message.answer(
                f"❌ Недостаточно средств на балансе. Вам не хватает {missing_amount} руб.\n\nПополните баланс для продолжения:",
                keyboard=get_payment_keyboard(payment_url)
            )
            # Clear state so they can pay and try again
            await self.state.clear_state(user_id)
            await self.state.clear_data(user_id)
            return


        await self.state.set_data(user_id, {"chosen_model": model, "session_type": session_type})

        if "motion" in model:
            await message.answer(
                "📸 Шаг 1: Пришлите фото (лицо):",
                keyboard=get_cancel_keyboard()
            )
        elif model == "grok_imagine":
            await message.answer(
                "📸 Шаг 1: Пришлите 1 фото для обработки:",
                keyboard=get_cancel_keyboard()
            )
        elif model == "qwen_image2":
            await message.answer(
                "📸 Шаг 1: Пришлите от 1 до 3 фото для обработки (в одном сообщении):",
                keyboard=get_cancel_keyboard()
            )
        else:
            await message.answer(
                "📸 Шаг 1: Пришлите от 1 до 8 фото для обработки (в одном сообщении):",
                keyboard=get_cancel_keyboard()
            )

        await self.state.set_state(user_id, "waiting_for_photo")
        return

    async def handle_photo_upload(self, message: Message, user_data: dict) -> str:
        """Handle photo upload"""
        user_id = message.from_id
        model = user_data.get("chosen_model", "nanabanana")

        # Check if message has photo
        if not message.attachments:
            await message.answer(
                "⚠️ Пожалуйста, пришлите фото.",
                keyboard=get_cancel_keyboard()
            )
            return

        # Get photo URL from attachment
        photo_urls = user_data.get("photo_urls", [])
        logger.info(f"VK handle_photo_upload: attachments count={len(message.attachments)}")
        for i, attachment in enumerate(message.attachments):
            logger.info(f"VK attachment {i}: type={attachment.type}")
            if attachment.type == "photo":
                photo_urls.append(attachment.photo.sizes[-1].url)
            elif attachment.type == "doc" and getattr(attachment.doc, "ext", "").lower() in ["jpg", "jpeg", "png", "webp"]:
                photo_urls.append(attachment.doc.url)

        if not photo_urls:
            await message.answer(
                "⚠️ Не удалось получить фото. Попробуй еще раз.",
                keyboard=get_cancel_keyboard()
            )
            return

        # Grok Imagine поддерживает максимум 1 фото, Qwen Image 2 — до 3, остальные — до 8
        max_photos = 1 if model == "grok_imagine" else (3 if model == "qwen_image2" else 8)

        # Save current photos
        user_data["photo_urls"] = photo_urls

        # Show collection keyboard if not reached max
        if len(photo_urls) < max_photos:
            await message.answer(
                f"📸 Фото {len(photo_urls)}/{max_photos} получено\n\n"
                f"Вы можете добавить еще фото или продолжить с текущими.",
                keyboard=get_photo_collection_keyboard(len(photo_urls), max_photos)
            )
            await self.state.set_state(user_id, "collecting_photos")
            await self.state.set_data(user_id, user_data)
            return

        # Max photos reached, proceed automatically
        if len(photo_urls) > max_photos:
            await message.answer(f"⚠️ Вы прикрепили больше {max_photos} фото. Мы будем использовать только первые {max_photos}.")
            user_data["photo_urls"] = photo_urls[:max_photos]

        await self._proceed_after_photos(message, user_data)

    async def _proceed_after_photos(self, message: Message, user_data: dict):
        """Continue workflow after collecting all photos"""
        user_id = message.from_id
        model = user_data.get("chosen_model", "nanabanana")

        if "motion" in model:
            await message.answer(
                "🎥 Шаг 2: Пришлите видео с движением\n\n"
                "⚠️ Важно: отправьте видео как Файл, иначе ВКонтакте заблокирует доступ к нему.\n\n"
                "Как отправить файл:\n"
                "📎 → Файл → выберите видео (.mp4) на вашем устройстве",
                keyboard=get_cancel_keyboard()
            )
            await self.state.set_state(user_id, "waiting_for_motion_video")
        elif model == "gpt5_image":
            # GPT-5 Image не поддерживает aspect_ratio — сразу к промпту
            user_data["aspect_ratio"] = "1:1"
            user_data["quality"] = "1K"
            await self.state.set_data(user_id, user_data)
            await message.answer(
                "✍️ Шаг 2: Описание изменений (или пропустить с '.'):\n\n"
                "✨ Не знаете что написать?\n"
                "💡 Готовые и проверенные промпты мы публикуем на стене нашей группы:\n"
                "👉 https://vk.com/club237140033",
                keyboard=get_cancel_keyboard()
            )
            await self.state.set_state(user_id, "waiting_for_prompt")
        else:
            from app.vk.keyboards import get_aspect_ratio_keyboard
            await message.answer(
                "📐 Шаг 2: Выберите соотношение сторон:",
                keyboard=get_aspect_ratio_keyboard(model)
            )
            await self.state.set_state(user_id, "waiting_for_aspect_ratio")

        await self.state.set_data(user_id, user_data)

    async def handle_photo_collection(self, message: Message, user_data: dict) -> str:
        """Handle photo collection state - adding more photos or proceeding"""
        user_id = message.from_id
        text = (message.text or "").strip().lower()
        model = user_data.get("chosen_model", "nanabanana")
        max_photos = 1 if model == "grok_imagine" else (3 if model == "qwen_image2" else 8)

        # Check for cancel
        if text in ("назад", "🔙 назад", "отмена"):
            await message.answer(
                "❌ Операция отменена.",
                keyboard=get_main_keyboard(user_id)
            )
            await self.state.clear_state(user_id)
            return

        # Check if user wants to proceed
        if "готово" in text or "продолжить" in text:
            await self._proceed_after_photos(message, user_data)
            return

        # Check if user wants to add more photos
        if "добавить" in text or message.attachments:
            # Handle new photo attachment
            if message.attachments:
                photo_urls = user_data.get("photo_urls", [])

                for i, attachment in enumerate(message.attachments):
                    if attachment.type == "photo":
                        photo_urls.append(attachment.photo.sizes[-1].url)
                    elif attachment.type == "doc" and getattr(attachment.doc, "ext", "").lower() in ["jpg", "jpeg", "png", "webp"]:
                        photo_urls.append(attachment.doc.url)

                if len(photo_urls) > max_photos:
                    photo_urls = photo_urls[:max_photos]
                    await message.answer(
                        f"⚠️ Достигнут лимит {max_photos} фото. Продолжаем с {max_photos} фото.",
                    )
                    user_data["photo_urls"] = photo_urls
                    await self._proceed_after_photos(message, user_data)
                    return

                user_data["photo_urls"] = photo_urls

                if len(photo_urls) < max_photos:
                    await message.answer(
                        f"📸 Фото {len(photo_urls)}/{max_photos} получено\n\n"
                        f"Вы можете добавить еще фото или продолжить с текущими.",
                        keyboard=get_photo_collection_keyboard(len(photo_urls), max_photos)
                    )
                    await self.state.set_data(user_id, user_data)
                else:
                    # Max reached
                    await self._proceed_after_photos(message, user_data)
                return
            else:
                # User clicked "add more" but didn't attach photo
                await message.answer(
                    "📸 Пришлите фото:",
                    keyboard=get_photo_collection_keyboard(len(user_data.get("photo_urls", [])), max_photos)
                )
                return

        # Unknown input
        await message.answer(
            "⚠️ Пожалуйста, выберите действие из меню или отправьте фото.",
            keyboard=get_photo_collection_keyboard(len(user_data.get("photo_urls", [])), max_photos)
        )

    async def handle_aspect_ratio(self, message: Message, user_data: dict) -> str:
        """Handle aspect ratio selection"""
        user_id = message.from_id
        text = (message.text or "").strip().lower()
        model = user_data.get("chosen_model", "nanabanana")
        
        if "пропустить" in text:
            user_data["aspect_ratio"] = "1:1"
        else:
            allowed = ["1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "21:9", "5:4", "4:5"]
            if text not in allowed:
                await message.answer("⚠️ Выберите соотношение из вариантов на клавиатуре.")
                return
            user_data["aspect_ratio"] = text
            
        await self.state.set_data(user_id, user_data)
        
        if model in ("seedream", "seedream_pro", "nanabanana_pro", "nanabanana_2"):
            from app.vk.keyboards import get_quality_keyboard
            await message.answer(
                "⚙️ Шаг 3: Выберите качество генерации:",
                keyboard=get_quality_keyboard(model)
            )
            await self.state.set_state(user_id, "waiting_for_quality")
        else:
            user_data["quality"] = "1K"
            await self.state.set_data(user_id, user_data)
            await message.answer(
                "✍️ Шаг 3: Описание изменений (или пропустить с '.'):\n\n"
                "✨ Не знаете что написать?\n"
                "💡 Готовые и проверенные промпты мы публикуем на стене нашей группы:\n"
                "👉 https://vk.com/club237140033",
                keyboard=get_cancel_keyboard()
            )
            await self.state.set_state(user_id, "waiting_for_prompt")
        return

    async def handle_quality(self, message: Message, user_data: dict) -> str:
        """Handle quality selection"""
        user_id = message.from_id
        text = (message.text or "").strip().lower()
        model = user_data.get("chosen_model", "nanabanana")
        
        if "пропустить" in text:
            user_data["quality"] = "basic" if model in ("seedream", "seedream_pro") else "1K"
        else:
            if "high" in text: user_data["quality"] = "high"
            elif "basic" in text: user_data["quality"] = "basic"
            elif "1k" in text: user_data["quality"] = "1K"
            elif "2k" in text: user_data["quality"] = "2K"
            elif "4k" in text: user_data["quality"] = "4K"
            else:
                await message.answer("⚠️ Выберите качество из вариантов на клавиатуре.")
                return
                
        await self.state.set_data(user_id, user_data)
        
        await message.answer(
            "✍️ Шаг 4: Описание изменений (или пропустить с '.'):\n\n"
            "✨ Не знаете что написать?\n"
            "💡 Готовые и проверенные промпты мы публикуем на стене нашей группы:\n"
            "👉 https://vk.com/club237140033",
            keyboard=get_cancel_keyboard()
        )
        await self.state.set_state(user_id, "waiting_for_prompt")
        return

    async def handle_motion_video_upload(self, message: Message, user_data: dict) -> str:
        """Handle motion video upload — with 3-strategy direct URL resolution."""
        user_id = message.from_id

        if not message.attachments:
            await message.answer(
                "⚠️ Пожалуйста, пришлите видео.\n\n"
                "📎 Нажмите → Файл → выберите .mp4 с устройства",
                keyboard=get_cancel_keyboard()
            )
            return

        # ── Разбираем вложение ───────────────────────────────────────────────
        doc_url = None

        for attachment in message.attachments:
            if attachment.type == "doc" and getattr(attachment.doc, "ext", "").lower() in ["mp4", "mov", "avi", "mkv"]:
                doc_url = attachment.doc.url
                logger.info(
                    f"📹 VK doc: owner={attachment.doc.owner_id}, "
                    f"id={attachment.doc.id}, url={doc_url[:80]}"
                )
                break
            elif attachment.type == "video":
                # Нативное VK-видео — ВК не даёт прямой URL для чужих аккаунтов.
                # Сразу просим переслать файлом.
                logger.info(f"📹 VK native video detected — rejecting, asking for file upload")
                await message.answer(
                    "❌ Вы отправили видео как нативное VK-видео.\n\n"
                    "ВКонтакте блокирует прямой доступ к таким видео — бот не сможет его обработать.\n\n"
                    "📎 Пожалуйста, отправьте то же видео как Файл:\n"
                    "Нажмите скрепку 📎 → Файл → выберите .mp4 с вашего устройства",
                    keyboard=get_cancel_keyboard()
                )
                return  # Ждём повторной отправки, состояние сохранено

        if not doc_url:
            await message.answer(
                "⚠️ Не удалось получить видео.\n\n📎 Нажмите → Файл → выберите .mp4 с устройства",
                keyboard=get_cancel_keyboard()
            )
            return

        # ── Скачиваем байты СРАЗУ пока URL горячий, льём на Catbox ───────────
        # doc.url — это редирект-ссылка VK (vk.ru/doc...), а не прямой .mp4.
        # Kling API такой URL не принимает. Решение: скачиваем → Catbox → прямой URL.
        await message.answer("🔄 Загружаю видео... (~30 сек)", keyboard=get_cancel_keyboard())

        try:
            # Шаг 1: скачиваем с VK (браузерные заголовки + HTML-парсер редиректов)
            async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as sess:
                video_bytes = await _download_vk_doc_video(sess, doc_url)

            if not video_bytes or len(video_bytes) < 1000:
                raise RuntimeError(f"Скачано слишком мало байт: {len(video_bytes) if video_bytes else 0}")

            logger.info(f"✅ Видео скачано: {len(video_bytes):,} байт. Заливаем на Catbox...")

            # Шаг 2: Catbox.moe → прямая https://files.catbox.moe/*.mp4
            form = aiohttp.FormData()
            form.add_field("reqtype", "fileupload")
            form.add_field("fileToUpload", video_bytes, filename="motion.mp4", content_type="video/mp4")

            async with aiohttp.ClientSession(connector=get_connector()) as sess:
                async with sess.post(
                    "https://catbox.moe/user/api.php",
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    catbox_url = (await resp.text()).strip()

            if not catbox_url.startswith("https://files.catbox.moe/"):
                raise RuntimeError(f"Catbox ответил неожиданно: {catbox_url[:100]}")

            logger.info(f"✅ Catbox URL: {catbox_url}")
            user_data["motion_video_url"] = catbox_url

        except Exception as e:
            logger.error(f"❌ Не удалось подготовить видео: {e}")
            await message.answer(
                "⚠️ Не удалось скачать видео с серверов ВКонтакте.\n\n"
                "Попробуйте:\n"
                "• Отправить видео заново\n"
                "• Убедитесь, что файл сохранён на устройстве (не из галереи VK)\n"
                "• Видео не должно превышать 500 МБ",
                keyboard=get_cancel_keyboard()
            )
            return

        await message.answer(
            "✅ Видео принято!\n\n"
            "✍️ Шаг 3: Опишите желаемое движение (или '.' для пропуска):\n\n"
            "✨ Не знаете что написать?\n"
            "💡 Готовые и красивые промпты мы публикуем на стене нашей группы:\n"
            "👉 https://vk.com/club237140033",
            keyboard=get_cancel_keyboard()
        )
        await self.state.set_state(user_id, "waiting_for_prompt")
        await self.state.set_data(user_id, user_data)
        return


    async def handle_prompt(self, message: Message, user_data: dict) -> str:
        """Handle prompt input and start generation"""
        user_id = message.from_id
        model = user_data.get("chosen_model", "nanabanana")
        photo_urls = user_data.get("photo_urls", [])
        session_type = user_data.get("session_type", "photo")
        prompt = (message.text or "").strip()

        # Checking prompt lengths based on models
        if "seedream" in model and len(prompt) > 2996:
            await message.answer("⚠️ Ваш текст превышает лимит в 2996 символов. Пожалуйста, сократите его и отправьте заново.", keyboard=get_cancel_keyboard())
            return
            
        if "nanabanana" in model and len(prompt) > 20000:
            await message.answer("⚠️ Ваш текст слишком длинный (максимум 20 000 символов). Пожалуйста, сократите его и отправьте заново.", keyboard=get_cancel_keyboard())
            return

        if ("flux" in model or "qwen" in model) and len(prompt) > 5000:
            await message.answer("⚠️ Ваш текст превышает лимит в 5000 символов. Пожалуйста, сократите его и отправьте заново.", keyboard=get_cancel_keyboard())
            return

        # Safety final balance check (should already be covered, just fallback)
        if not await has_balance(user_id, model):
            await self.state.clear_state(user_id)
            await self.state.clear_data(user_id)
            await message.answer(
                "❌ Недостаточно средств. Выберите модель заново для расчета.",
                keyboard=get_main_keyboard(user_id)
            )
            return

        if not photo_urls:
            await self.state.clear_state(user_id)
            await self.state.clear_data(user_id)
            await message.answer(
                "⚠️ Фото не найдено. Начните заново.",
                keyboard=get_main_keyboard(user_id)
            )
            return

        # Start generation
        if "motion" in model:
            motion_video_url = user_data.get("motion_video_url")
            motion_doc_ref = user_data.get("motion_doc_ref")
            task = asyncio.create_task(
                background_video_gen(
                    self.bot,
                    user_id,
                    photo_urls[0],
                    prompt,
                    model,
                    motion_video_url=motion_video_url,
                    motion_doc_ref=motion_doc_ref
                )
            )
            time_msg = "⏳ Магия началась! Motion Control занимает 7-12 минут."
        elif "kling" in model.lower():
            task = asyncio.create_task(
                background_video_gen(
                    self.bot,
                    user_id,
                    photo_urls[0],
                    prompt,
                    model
                )
            )
            time_msg = "⏳ Генерация видео началась (3-5 мин)."
        else:
            aspect_ratio = user_data.get("aspect_ratio", "1:1")
            quality = user_data.get("quality", "1K")
            task = asyncio.create_task(
                background_photo_gen(
                    self.bot,
                    user_id,
                    photo_urls,
                    prompt,
                    model,
                    aspect_ratio,
                    quality
                )
            )
            time_msg = "⏳ Генерация фото началась (1-2 мин)."

        active_tasks.add(task)
        task.add_done_callback(active_tasks.discard)

        await message.answer(time_msg, keyboard=get_main_keyboard(user_id))
        await self.state.clear_state(user_id)
        await self.state.clear_data(user_id)
        return

    async def handle_balance(self, message: Message) -> str:
        """Show user balance"""
        user_id = message.from_id
        try:
            balance = await db.get_balance(user_id)
            balance_text = (
                f"👤 Ваш профиль\n\n"
                f"🆔 ID: {user_id}\n"
                f"💰 Мой баланс: {balance} руб."
            )
            await message.answer(
                balance_text,
                keyboard=get_main_keyboard(user_id)
            )
        except Exception as e:
            logger.error(f"❌ Balance check error: {e}")
            await message.answer(
                "⚠️ Ошибка при получении баланса.",
                keyboard=get_main_keyboard(user_id)
            )
        return

    async def handle_deposit(self, message: Message) -> str:
        """Handle deposit/payment"""
        user_id = message.from_id
        await message.answer(
            "💳 Введите сумму в рублях, на которую хотите пополнить баланс (например: 150):",
            keyboard=get_cancel_keyboard()
        )
        await self.state.set_state(user_id, "waiting_for_deposit_amount")
        return

    async def handle_deposit_amount(self, message: Message, user_data: dict) -> str:
        """Handle deposit amount input and generate link"""
        user_id = message.from_id
        text = (message.text or "").strip()
        
        try:
            amount = int(text)
            if amount < 10:
                await message.answer("⚠️ Минимальная сумма пополнения: 10 руб.", keyboard=get_cancel_keyboard())
                return
                
            from app.config import settings
            from urllib.parse import urlencode
            from app.vk.keyboards import get_payment_keyboard
            
            params = {
                "do": "pay",
                "order_id": f"{user_id}_{amount}",
                "products[0][name]": "Генерация с помощью нейросети",
                "products[0][price]": amount,
                "products[0][quantity]": 1
            }
            payment_url = f"{settings.vk_prodamus_url}/?{urlencode(params, encoding='windows-1251')}"
            
            await message.answer(
                f"💰 К оплате: {amount} руб.",
                keyboard=get_payment_keyboard(payment_url)
            )
            await self.state.clear_state(user_id)
            await self.state.clear_data(user_id)
            
            # Возвращаем основную клавиатуру в следующем сообщении
            await message.answer(
                "После оплаты средства автоматически поступят на ваш баланс.",
                keyboard=get_main_keyboard(user_id)
            )
        except ValueError:
            await message.answer(
                "⚠️ Пожалуйста, введите корректное число (например: 150):",
                keyboard=get_cancel_keyboard()
            )
            
        return

    async def handle_help(self, message: Message) -> str:
        """Show help"""
        user_id = message.from_id
        help_text = "По любым вопросам или проблемам (включая пополнение) пишите в нашу поддержку: @esya0010"
        await message.answer(help_text, keyboard=get_main_keyboard(user_id))
        return

    async def handle_referral_menu(self, message: Message) -> None:
        user_id = message.from_id
        try:
            await db.create_new_user(user_id)
            total_e, avail = await db.get_referral_stats(user_id)
            refs_count = await db.get_referrals_count(user_id)
        except Exception as e:
            logger.error(f"referral menu DB: {e}")
            await message.answer("⚠️ Не удалось загрузить данные.", keyboard=get_main_keyboard(user_id))
            return

        invite_lines = [
            f"🆔 Ваш ID: {user_id}",
        ]
        if settings.vk_group_id:
            invite_link = f"https://vk.com/write-{settings.vk_group_id}?ref=user_{user_id}"
            invite_lines.extend([
                "",
                "🔗 Ваша персональная пригласительная ссылка:",
                invite_link,
                "",
                "📌 Как это работает:",
                "• Друг переходит по ссылке и пишет боту любое сообщение",
                "• Если он у нас впервые — он автоматически закрепится за вами",
                "• Вы получаете 30% от каждого его пополнения",
                "",
                "⚠️ Если друг уже писал нашему боту раньше, ссылка не сработает.",
                "В этом случае попросите его написать команду:",
                f"  /start {user_id}",
            ])
        else:
            invite_lines.extend([
                "",
                "Попросите друга написать боту команду:",
                f"  /start {user_id}",
                f"  или /start ref{user_id}",
            ])

        body = (
            "💎 Зарабатывайте вместе с Mira Promt\n\n"
            "За каждое пополнение баланса приглашённым пользователем вам начисляется 30% от суммы "
            "платежа на отдельный реферальный счёт (не путать с балансом для генераций).\n\n"
            f"👥 Приглашено рефералов: {refs_count}\n"
            f"📊 Всего начислено с партнёрки: {total_e} руб.\n"
            f"💵 Доступно к выводу: {avail} руб.\n\n"
            + "\n".join(invite_lines)
        )
        await message.answer(body, keyboard=get_referral_section_keyboard())

    async def handle_referral_withdraw_start(self, message: Message) -> None:
        user_id = message.from_id
        _, avail = await db.get_referral_stats(user_id)
        if avail < MIN_REFERRAL_WITHDRAW:
            await message.answer(
                f"⚠️ Минимум для вывода: {MIN_REFERRAL_WITHDRAW} руб. "
                f"Сейчас доступно: {avail} руб.",
                keyboard=get_referral_section_keyboard(),
            )
            return
        await self.state.set_state(user_id, "waiting_referral_withdraw_amount")
        await self.state.set_data(user_id, {})
        await message.answer(
            f"💵 Введите сумму вывода в рублях (целое число).\n"
            f"Доступно: {avail} руб. Минимум: {MIN_REFERRAL_WITHDRAW} руб.",
            keyboard=get_cancel_keyboard(),
        )

    async def handle_referral_withdraw_amount(self, message: Message, user_data: dict) -> None:
        user_id = message.from_id
        raw = (message.text or "").strip()
        try:
            amount = int(raw)
        except ValueError:
            await message.answer("⚠️ Введите целое число рублей.", keyboard=get_cancel_keyboard())
            return
        _, avail = await db.get_referral_stats(user_id)
        if amount < MIN_REFERRAL_WITHDRAW:
            await message.answer(
                f"⚠️ Сумма не меньше {MIN_REFERRAL_WITHDRAW} руб.",
                keyboard=get_cancel_keyboard(),
            )
            return
        if amount > avail:
            await message.answer(
                f"⚠️ Недостаточно средств. Доступно: {avail} руб.",
                keyboard=get_cancel_keyboard(),
            )
            return
        user_data["withdraw_amount"] = amount
        await self.state.set_data(user_id, user_data)
        await self.state.set_state(user_id, "waiting_referral_withdraw_method")
        await message.answer(
            "💳 Укажите способ вывода (например: СБП, карта, банковский перевод):",
            keyboard=get_cancel_keyboard(),
        )

    async def handle_referral_withdraw_method(self, message: Message, user_data: dict) -> None:
        method = (message.text or "").strip()
        if not method or len(method) < 2:
            await message.answer("⚠️ Укажите корректный способ вывода.", keyboard=get_cancel_keyboard())
            return
        lowered = method.lower()
        if "крипт" in lowered or "usdt" in lowered or "btc" in lowered or "eth" in lowered:
            await message.answer(
                "⚠️ Вывод в криптовалюте недоступен. Выберите СБП, карту или банковский перевод.",
                keyboard=get_cancel_keyboard(),
            )
            return
        user_data["withdraw_method"] = method
        user_id = message.from_id
        await self.state.set_data(user_id, user_data)
        await self.state.set_state(user_id, "waiting_referral_withdraw_details")
        await message.answer(
            "📝 Теперь укажите реквизиты для перевода этим способом:",
            keyboard=get_cancel_keyboard(),
        )

    async def handle_referral_withdraw_details(self, message: Message, user_data: dict) -> None:
        user_id = message.from_id
        details = (message.text or "").strip()
        amount = int(user_data.get("withdraw_amount") or 0)
        method = (user_data.get("withdraw_method") or "").strip()
        if not details or len(details) < 5:
            await message.answer("⚠️ Опишите реквизиты подробнее.", keyboard=get_cancel_keyboard())
            return
        if not method:
            await message.answer("⚠️ Способ вывода не указан. Начните заявку заново.", keyboard=get_main_keyboard(user_id))
            await self.state.clear_state(user_id)
            await self.state.clear_data(user_id)
            return

        full_details = f"Способ: {method}\nРеквизиты: {details}"
        req_id = await db.create_withdrawal_request(user_id, amount, full_details)
        await self.state.clear_state(user_id)
        await self.state.clear_data(user_id)
        if not req_id:
            await message.answer(
                "⚠️ Не удалось создать заявку. Проверьте сумму и попробуйте снова.",
                keyboard=get_main_keyboard(user_id),
            )
            return

        await message.answer(
            f"✅ Заявка №{req_id} отправлена администратору. Сумма: {amount} руб.\n"
            "Ожидайте перевода.",
            keyboard=get_main_keyboard(user_id),
        )

        admin_text = (
            f"📤 Новая заявка на вывод реферальных средств\n\n"
            f"№ заявки: {req_id}\n"
            f"Пользователь: vk.com/id{user_id}\n"
            f"🆔 ID: {user_id}\n"
            f"💵 Сумма: {amount} руб.\n"
            f"💳 Способ вывода: {method}\n\n"
            f"Реквизиты:\n{details}"
        )
        for admin_id in settings.vk_admin_ids:
            try:
                await self.bot.api.messages.send(
                    user_id=admin_id,
                    message=admin_text,
                    keyboard=get_admin_withdraw_complete_keyboard(req_id),
                    random_id=0,
                )
            except Exception as e:
                logger.error(f"Не удалось отправить заявку админу {admin_id}: {e}")

    async def _answer_message_event(self, event: GroupTypes.MessageEvent, snackbar: str) -> None:
        await self.bot.api.messages.send_message_event_answer(
            event_id=event.object.event_id,
            user_id=event.object.user_id,
            peer_id=event.object.peer_id,
            event_data=ShowSnackbarEvent(text=snackbar).model_dump_json(),
        )

    async def on_message_event(self, event: GroupTypes.MessageEvent) -> None:
        """Callback-кнопка «Завершено» у заявки на вывод (только админы)."""
        uid = event.object.user_id
        if uid not in settings.vk_admin_ids:
            await self._answer_message_event(event, "Нет доступа")
            return

        payload = event.object.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                await self._answer_message_event(event, "Ошибка данных")
                return
        if not isinstance(payload, dict) or payload.get("action") != "referral_withdraw_done":
            return

        rid = payload.get("rid")
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            await self._answer_message_event(event, "Неверная заявка")
            return

        done = await db.complete_withdrawal_request(rid)
        if not done:
            await self._answer_message_event(event, "Уже выполнено или заявка не найдена")
            return

        target_uid, amount = done
        await self._answer_message_event(event, "Заявка закрыта")

        cmid = getattr(event.object, "conversation_message_id", None)
        if cmid is not None:
            try:
                new_text = (
                    f"✅ ВЫПОЛНЕНО (заявка №{rid})\n\n"
                    f"Пользователь: vk.com/id{target_uid}\n"
                    f"Сумма: {amount} руб."
                )
                await self.bot.api.messages.edit(
                    peer_id=event.object.peer_id,
                    conversation_message_id=cmid,
                    message=new_text,
                )
            except Exception as e:
                logger.error(f"messages.edit после вывода: {e}")

        try:
            await self.bot.api.messages.send(
                user_id=target_uid,
                message=(
                    f"✅ Заявка на вывод №{rid} на сумму {amount} руб. отмечена как выполненная.\n"
                    "Спасибо, что с нами!"
                ),
                keyboard=get_main_keyboard(target_uid),
                random_id=0,
            )
        except Exception as e:
            logger.error(f"Уведомление пользователю {target_uid}: {e}")
