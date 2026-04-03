from vkbottle import Keyboard, KeyboardButtonColor, Text, OpenLink


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
    kb.add(Text("🆘 Помощь"), color=KeyboardButtonColor.SECONDARY)
    
    if user_id and user_id in settings.vk_admin_ids:
        kb.row()
        kb.add(Text("🛡 Админ панель"), color=KeyboardButtonColor.NEGATIVE)

    return kb.get_json()


def get_model_keyboard() -> str:
    """Выбор модели фото — аналог model_inline() в Telegram"""
    kb = Keyboard(one_time=True, inline=False)
    kb.add(Text("🌊 SeeDream 5.0 Lite — 26 руб."), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("🍌 NanoBanana — 17 руб."), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("🍌 NanoBanana 2 — 28 руб."), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("💎 NanoBanana PRO — 55 руб."), color=KeyboardButtonColor.PRIMARY)
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


def get_empty_keyboard() -> str:
    """Пустая клавиатура (скрыть кнопки)"""
    return Keyboard(one_time=True).get_json()
