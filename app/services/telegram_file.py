import os
import aiohttp
import logging
from aiogram import Bot
from typing import Optional  # Теперь будет использоваться


async def get_telegram_photo_url(bot: Bot, file_id: str) -> Optional[str]:
    """
    Для фото: пробует Telegraph, если не выходит — дает прямую ссылку.
    Для видео: сразу дает прямую ссылку (Telegraph не поддерживает видео).
    """
    token = os.getenv("BOT_TOKEN")
    if not token:
        logging.error("❌ BOT_TOKEN не найден в переменных окружения")
        return None

    try:
        # 1. Получаем объект файла из Telegram
        file = await bot.get_file(file_id)
        tg_url = f"https://api.telegram.org/file/bot{token}/{file.file_path}"

        # Если это видео, сразу возвращаем прямую ссылку
        if any(ext in file.file_path.lower() for ext in [".mp4", ".mov", ".avi"]):
            logging.info(f"🎥 Видео обнаружено, используем прямую ссылку: {tg_url}")
            return tg_url

        # 2. Пытаемся залить на Telegraph (только для фото)
        async with aiohttp.ClientSession() as session:
            async with session.get(tg_url) as resp:
                if resp.status != 200:
                    logging.warning(f"⚠️ Не удалось скачать файл из TG, статус: {resp.status}")
                    return tg_url
                file_data = await resp.read()

            form = aiohttp.FormData()
            form.add_field('file', file_data, filename='image.jpg', content_type='image/jpeg')

            async with session.post('https://telegra.ph/upload', data=form) as up_resp:
                if up_resp.status == 200:
                    result = await up_resp.json()
                    if isinstance(result, list) and len(result) > 0:
                        path = result[0].get('src')
                        res_url = f"https://telegra.ph{path}"
                        logging.info(f"✅ Фото на Telegraph: {res_url}")
                        return res_url

                logging.warning(f"⚠️ Telegraph (код {up_resp.status}), используем прямую ссылку")
                return tg_url

    except Exception as e:
        logging.error(f"❌ Ошибка в get_telegram_photo_url: {e}")
        # Крайний случай: пытаемся вернуть хотя бы ссылку на API Telegram
        return f"https://api.telegram.org/file/bot{token}/{file_id}"  # file_id как заплатку