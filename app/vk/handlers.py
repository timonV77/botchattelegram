"""VK Message Handlers - Complete implementation mirroring Telegram"""
import logging
import asyncio
import traceback
import json
from typing import Optional, List
from vkbottle.bot import Bot, Message
from vkbottle import PhotoMessageUploader, VideoUploader

from app.vk.keyboards import (
    get_main_keyboard,
    get_model_keyboard,
    get_video_model_keyboard,
    get_cancel_keyboard,
    get_admin_keyboard,
)
from app.vk.state_manager import VKStateManager
from app.vk.file_handler import download_vk_photo, download_vk_video, bytes_to_base64_data_uri
from app.network import get_connector, timeout_config
from app.vk.models.video.kling_motion import _download_vk_doc_video
from app.vk.generation import (
    has_balance, charge, generate_photo as generate, generate_video, COSTS
)
from app.services.telegram_file import get_telegram_photo_url, download_telegram_file
import vk_database as db
from app.config import settings

logger = logging.getLogger(__name__)

MODEL_NAMES = {
    "nanabanana": "🍌 NanoBanana",
    "nanabanana_2": "🍌 NanoBanana 2",
    "nanabanana_pro": "💎 NanoBanana PRO",
    "seedream": "🌊 SeeDream 5.0 Lite",
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
):
    """Background photo generation task"""
    try:
        # Prepare photo sources
        photo_sources = await _build_image_sources(photo_urls, force_data_uri=False)

        if model in ("nanabanana_pro", "seedream"):
            photo_sources = [
                s for s in photo_sources
                if isinstance(s, str) and (s.startswith("http://") or s.startswith("https://"))
            ]
            logger.info(f"{model} filtered url_sources={len(photo_sources)}")

        if not photo_sources:
            await bot.api.messages.send(
                user_id=user_id,
                message="⚠️ Не удалось подготовить фото-референс.",
                random_id=0
            )
            return

        # Generate
        result = await generate(image_urls=photo_sources, prompt=prompt, model=model)

        if not result or not result[0]:
            await bot.api.messages.send(
                user_id=user_id,
                message="⚠️ Не удалось получить результат от нейросети.",
                random_id=0
            )
            return

        img_bytes, ext, _ = result

        # Upload photo to VK
        photo_uploader = PhotoMessageUploader(bot.api)
        attachment = await photo_uploader.upload(img_bytes)

        # Send result photo
        await bot.api.messages.send(
            user_id=user_id,
            message=f"✨ Ваше изображение готово! ({MODEL_NAMES.get(model)})",
            attachment=attachment,
            keyboard=get_main_keyboard(user_id),
            random_id=0
        )

        # Charge user
        await charge(user_id, model)
        logger.info(f"✅ Photo generated for VK user {user_id}")

    except Exception as e:
        logger.error(f"❌ Photo generation error: {traceback.format_exc()}")
        await bot.api.messages.send(
            user_id=user_id,
            message="⚠️ Ошибка при создании фото.",
            keyboard=get_main_keyboard(user_id),
            random_id=0
        )


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
    vk_video_id: Optional[str] = None,
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

        # Если это видео-вложение из ВК (не документ)
        if vk_video_id:
            from app.vk.video_proxy import get_direct_video_and_upload
            logger.info(f"🔄 Извлечение прямой ссылки для видео {vk_video_id}...")
            catbox_url = await get_direct_video_and_upload(vk_video_id)
            if catbox_url:
                logger.info(f"✅ Итоговая прямая ссылка для Kling: {catbox_url}")
                motion_video_url = catbox_url
            else:
                logger.warning("⚠️ Не удалось получить ссылку через proxy, используем исходный URL")

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
        if "отменить" in text or "❌" in text or "назад" in text or "🔙" in text:
            await self.state.clear_state(user_id)
            await self.state.clear_data(user_id)
            await message.answer(
                "🔙 Вы вернулись в главное меню.",
                keyboard=get_main_keyboard(user_id)
            )
            return

        # --- ADMIN PANEL ---
        elif is_admin and ("🛡" in text or "админ" in text):
            return await self.handle_admin_panel(message)
        
        elif is_admin and "👥 пользователи" in text:
            return await self.handle_admin_stats(message)

        elif is_admin and "💳 выдать баланс" in text:
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

        # --- PHOTO SESSION ---
        elif "начать фотосессию" in text or text == "📸 начать фотосессию":
            return await self.handle_start_photo(message)

        # --- VIDEO SESSION ---
        elif "оживить фото" in text or text == "🎬 оживить фото":
            return await self.handle_start_video(message)

        # --- BALANCE ---
        elif "мой баланс" in text or "💰" in text:
            return await self.handle_balance(message)

        # --- DEPOSIT ---
        elif "пополнить" in text or "💳" in text:
            return await self.handle_deposit(message)

        # --- HELP ---
        elif "помощь" in text or "🆘" in text:
            return await self.handle_help(message)

        # --- STATE-BASED HANDLERS ---
        elif state == "waiting_for_model":
            return await self.handle_model_choice(message, user_data)

        elif state == "waiting_for_photo":
            return await self.handle_photo_upload(message, user_data)

        elif state == "waiting_for_motion_video":
            return await self.handle_motion_video_upload(message, user_data)

        elif state == "waiting_for_prompt":
            return await self.handle_prompt(message, user_data)
            
        elif state == "waiting_for_deposit_amount":
            return await self.handle_deposit_amount(message, user_data)

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
        
        # 1. Check text arguments: /start 12345 or start 12345
        parts = text.split()
        if len(parts) > 1:
            ref_part = parts[1].replace("ref", "")
            if ref_part.isdigit():
                referrer_id = int(ref_part)

        # 2. Check payload (if passed via VK Mini Apps or buttons)
        payload = getattr(message, "payload", None)
        if payload and not referrer_id:
            try:
                payload_obj = json.loads(payload) if isinstance(payload, str) else payload
                ref_from_payload = payload_obj.get("ref") or payload_obj.get("referrer")
                if str(ref_from_payload).isdigit():
                    referrer_id = int(ref_from_payload)
            except: pass

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
        if "pro" in text or "💎" in text:
            model = "nanabanana_pro"
        elif "2" in text and "nanabanana" in text:
            model = "nanabanana_2"
        elif "nanabanana" in text or "🍌" in text:
            model = "nanabanana"
        elif "seedream" in text or "🌊" in text or "5.0" in text or "lite" in text:
            model = "seedream"
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
        else:
            await message.answer(
                "📸 Шаг 1: Пришлите фото для обработки:",
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
        photo_url = None
        for attachment in message.attachments:
            if attachment.type == "photo":
                # Get the largest size available
                photo_url = attachment.photo.sizes[-1].url
                break
            elif attachment.type == "doc" and getattr(attachment.doc, "ext", "").lower() in ["jpg", "jpeg", "png", "webp"]:
                photo_url = attachment.doc.url
                break

        if not photo_url:
            await message.answer(
                "⚠️ Не удалось получить фото. Попробуй еще раз.",
                keyboard=get_cancel_keyboard()
            )
            return

        user_data["photo_urls"] = [photo_url]

        if "motion" in model:
            await message.answer(
                "🎥 Шаг 2: Пришлите видео с движением:",
                keyboard=get_cancel_keyboard()
            )
            await self.state.set_state(user_id, "waiting_for_motion_video")
        else:
            await message.answer(
                "✍️ Шаг 2: Описание изменений (или пропустить с '.'):",
                keyboard=get_cancel_keyboard()
            )
            await self.state.set_state(user_id, "waiting_for_prompt")

        await self.state.set_data(user_id, user_data)
        return

    async def handle_motion_video_upload(self, message: Message, user_data: dict) -> str:
        """Handle motion video upload"""
        user_id = message.from_id

        # Check if message has video
        if not message.attachments:
            await message.answer(
                "⚠️ Пожалуйста, пришлите видео.",
                keyboard=get_cancel_keyboard()
            )
            return

        # Get video URL from attachment
        video_url = None
        doc_owner_id = None
        doc_id = None
        doc_access_key = None
        for attachment in message.attachments:
            if attachment.type == "doc" and getattr(attachment.doc, "ext", "").lower() in ["mp4", "mov", "avi", "mkv"]:
                video_url = attachment.doc.url
                doc_owner_id = attachment.doc.owner_id
                doc_id = attachment.doc.id
                doc_access_key = getattr(attachment.doc, "access_key", None)
                logger.info(f"📹 VK doc: owner={doc_owner_id}, id={doc_id}, url={video_url}, access_key={doc_access_key}")
                break
            elif attachment.type == "video":
                video_id = f"{attachment.video.owner_id}_{attachment.video.id}"
                video_url = f"https://vk.com/video{video_id}"
                if getattr(attachment.video, "access_key", None):
                    video_id += f"_{attachment.video.access_key}"
                    video_url += f"_{attachment.video.access_key}"
                logger.info(f"📹 VK video ID passed directly: {video_id}")
                user_data["vk_video_id"] = video_id
                user_data["motion_video_url"] = video_url
                user_data["motion_video_pre_uploaded"] = True
                pre_uploaded_video = True
                break
        if not video_url:
            await message.answer(
                "⚠️ Не удалось получить видео. Пожалуйста, отправьте видео **как Видео или Документ (📎 → Файл)**.",
                keyboard=get_cancel_keyboard()
            )
            return

        pre_uploaded_video = user_data.get("motion_video_pre_uploaded", False)

        if not pre_uploaded_video:
            # Сразу скачиваем и перезаливаем видео на публичный хостинг,
            # пока URL ещё "горячий" и не требует авторизации VK
            import aiohttp
            from app.network import get_connector, timeout_config
            await message.answer("🔄 Принимаю видео...", keyboard=get_cancel_keyboard())
            try:
                async with aiohttp.ClientSession(connector=get_connector(), timeout=timeout_config) as sess:
                    video_bytes = await _download_vk_doc_video(sess, video_url)
                if video_bytes:
                    try:
                        from vkbottle import VideoUploader
                        video_uploader = VideoUploader(self.bot.api)
                        attachment = await video_uploader.upload(file_source=video_bytes, name=f"motion_ref_{user_id}.mp4")
                        public_video_url = f"https://vk.com/{attachment}"
                        logger.info(f"✅ Видео загружено в VK video.save: {public_video_url}")
                        user_data["motion_video_url"] = public_video_url
                        user_data["motion_video_pre_uploaded"] = True
                    except Exception as up_err:
                        logger.warning(f"⚠️ Ошибка загрузки видео в VK: {up_err}, fallback to doc URL")
                        user_data["motion_video_url"] = video_url
                        if doc_owner_id and doc_id:
                            ref = f"{doc_owner_id}_{doc_id}"
                            if doc_access_key: ref += f"_{doc_access_key}"
                            user_data["motion_doc_ref"] = ref
                else:
                    logger.warning("⚠️ Не удалось скачать видео сразу, будем пробовать позже")
                    user_data["motion_video_url"] = video_url
                    if doc_owner_id and doc_id:
                        ref = f"{doc_owner_id}_{doc_id}"
                        if doc_access_key: ref += f"_{doc_access_key}"
                        user_data["motion_doc_ref"] = ref
            except Exception as e:
                logger.error(f"❌ Ошибка предзагрузки видео: {e}")
                user_data["motion_video_url"] = video_url
                if doc_owner_id and doc_id:
                    ref = f"{doc_owner_id}_{doc_id}"
                if doc_access_key: ref += f"_{doc_access_key}"
                user_data["motion_doc_ref"] = ref

        await message.answer(
            "✍️ Шаг 3: Описание (или '.' для пропуска):",
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
            vk_video_id = user_data.get("vk_video_id")
            task = asyncio.create_task(
                background_video_gen(
                    self.bot,
                    user_id,
                    photo_urls[0],
                    prompt,
                    model,
                    motion_video_url=motion_video_url,
                    motion_doc_ref=motion_doc_ref,
                    vk_video_id=vk_video_id
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
            task = asyncio.create_task(
                background_photo_gen(
                    self.bot,
                    user_id,
                    photo_urls,
                    prompt,
                    model
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
