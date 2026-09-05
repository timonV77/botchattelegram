from vkbottle import Keyboard, KeyboardButtonColor, Text, OpenLink, Callback

# Главное меню VK — партнёрка (до 40 символов на кнопку ВК)
VK_REFERRAL_MENU_BUTTON = "Зарабатывать вместе с Mira Promt"
VK_REFERRAL_WITHDRAW_BUTTON = "💵 Заявка на вывод"
VK_REFERRAL_BACK_BUTTON = "🔙 В главное меню"


def get_payment_keyboard(url: str) -> str:
    """Кнопка для перехода к оплате"""
    kb = Keyboard(one_time=False, inline=True)
    kb.add(OpenLink(link=url, label="💳 Перейти к оплате"))
    return kb.get_json()


def get_admin_keyboard() -> str:
    """Клавиатура панели администратора"""
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text("👥 Пользователи"), color=KeyboardButtonColor.PRIMARY)
    kb.add(Text("💳 Выдать баланс"), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("🔙 Назад"), color=KeyboardButtonColor.NEGATIVE)
    return kb.get_json()


from app.config import settings

def get_main_keyboard(user_id: int | None = None) -> str:
    """Главное меню — аналог main_kb() в Telegram"""
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text("📸 Начать фотосессию"), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("🎬 Оживить фото"), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("💰 Мой баланс"), color=KeyboardButtonColor.SECONDARY)
    kb.add(Text("💳 Пополнить"), color=KeyboardButtonColor.SECONDARY)
    kb.row()
    kb.add(Text(VK_REFERRAL_MENU_BUTTON), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("🆘 Помощь"), color=KeyboardButtonColor.SECONDARY)
    
    if user_id and user_id in settings.vk_admin_ids:
        kb.row()
        kb.add(Text("🛡 Админ панель"), color=KeyboardButtonColor.NEGATIVE)

    return kb.get_json()


def get_model_keyboard() -> str:
    """Выбор модели фото — аналог model_inline() в Telegram"""
    kb = Keyboard(one_time=True, inline=False)
    kb.add(Text("🌊 SeeDream 5.0 Lite — 26 руб."), color=KeyboardButtonColor.PRIMARY)
    kb.add(Text("🌊 SeeDream 5.0 Pro — 19 руб."), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("🍌 NanoBanana — 17 руб."), color=KeyboardButtonColor.POSITIVE)
    kb.add(Text("🍌 NanoBanana 2 — 28 руб."), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("💎 NanoBanana PRO — 39 руб."), color=KeyboardButtonColor.PRIMARY)
    kb.add(Text("🔮 Qwen Image 2 — 19 руб."), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("⚡ Flux-2 Pro — 22 руб."), color=KeyboardButtonColor.POSITIVE)
    kb.add(Text("⚡ Flux-2 Flex — 45 руб."), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("🤖 Grok — 14 руб."), color=KeyboardButtonColor.POSITIVE)
    kb.add(Text("🧠 GPT-5 — 25 руб."), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("🔙 Назад"), color=KeyboardButtonColor.NEGATIVE)
    return kb.get_json()


def get_video_model_keyboard() -> str:
    """Выбор модели видео — только Motion Control с выбором качества"""
    kb = Keyboard(one_time=True, inline=False)
    kb.add(Text("🎬 Motion 720p — 14р/сек"), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("🎬 Motion 1080p — 20р/сек"), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("🔙 Назад"), color=KeyboardButtonColor.NEGATIVE)
    return kb.get_json()


def get_cancel_keyboard() -> str:
    """Кнопка отмены — аналог cancel_kb() в Telegram"""
    kb = Keyboard(one_time=True, inline=False)
    kb.add(Text("🔙 Назад"), color=KeyboardButtonColor.NEGATIVE)
    return kb.get_json()


def get_photo_collection_keyboard(current_count: int, max_count: int) -> str:
    """Клавиатура для сбора нескольких фото"""
    kb = Keyboard(one_time=True, inline=False)
    kb.add(Text(f"➕ Добавить еще фото ({current_count}/{max_count})"), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("✅ Готово, продолжить"), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("🔙 Назад"), color=KeyboardButtonColor.NEGATIVE)
    return kb.get_json()


def get_empty_keyboard() -> str:
    """Пустая клавиатура (скрыть кнопки)"""
    return Keyboard(one_time=True).get_json()


def get_referral_section_keyboard() -> str:
    """Меню раздела партнёрки"""
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text(VK_REFERRAL_WITHDRAW_BUTTON), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text(VK_REFERRAL_BACK_BUTTON), color=KeyboardButtonColor.NEGATIVE)
    return kb.get_json()


def get_admin_withdraw_complete_keyboard(request_id: int) -> str:
    """Inline: админ подтверждает перевод по заявке"""
    kb = Keyboard(one_time=False, inline=True)
    kb.add(
        Callback(
            "✅ Завершено",
            payload={"action": "referral_withdraw_done", "rid": request_id},
        )
    )
    return kb.get_json()


def get_aspect_ratio_keyboard(model: str) -> str:
    """Клавиатура выбора соотношения сторон"""
    kb = Keyboard(one_time=True, inline=False)
    
    if model == "grok_imagine":
        ratios = ["1:1", "2:3", "3:2"]
    elif model == "seedream":
        ratios = ["1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "21:9"]
    elif model in ("seedream_pro", "flux2_pro", "flux2_flex"):
        ratios = ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3"]
    elif model == "qwen_image2":
        ratios = ["1:1", "3:4", "4:3", "9:16", "16:9"]
    else:
        # nanabanana, nanabanana_2, nanabanana_pro
        ratios = ["1:1", "9:16", "16:9", "3:4", "4:3", "3:2", "2:3", "5:4", "4:5", "21:9"]
    
    # По 3 кнопки в ряд
    for i, ratio in enumerate(ratios):
        kb.add(Text(ratio), color=KeyboardButtonColor.SECONDARY)
        if (i + 1) % 3 == 0 and (i + 1) != len(ratios):
            kb.row()
            
    kb.row()
    kb.add(Text("⏭ Пропустить (1:1)"), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("🔙 Назад"), color=KeyboardButtonColor.NEGATIVE)
    return kb.get_json()


def get_quality_keyboard(model: str) -> str:
    """Клавиатура выбора качества"""
    kb = Keyboard(one_time=True, inline=False)
    
    if model in ("seedream", "seedream_pro"):
        kb.add(Text("basic"), color=KeyboardButtonColor.SECONDARY)
        kb.add(Text("high"), color=KeyboardButtonColor.SECONDARY)
        kb.row()
        kb.add(Text("⏭ Пропустить (basic)"), color=KeyboardButtonColor.PRIMARY)
    elif model in ("nanabanana_pro", "nanabanana_2"):
        kb.add(Text("1K"), color=KeyboardButtonColor.SECONDARY)
        kb.add(Text("2K"), color=KeyboardButtonColor.SECONDARY)
        kb.add(Text("4K"), color=KeyboardButtonColor.SECONDARY)
        kb.row()
        kb.add(Text("⏭ Пропустить (1K)"), color=KeyboardButtonColor.PRIMARY)
        
    kb.row()
    kb.add(Text("🔙 Назад"), color=KeyboardButtonColor.NEGATIVE)
    return kb.get_json()
