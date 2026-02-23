import os
import aiohttp
import logging
from aiogram import Bot
from typing import Optional


async def get_telegram_photo_url(bot: Bot, file_id: str) -> str:
    """
    Скачивает фото из Telegram и перезаливает его на Telegraph,
    чтобы обеспечить стабильный доступ нейросетям (Seedream, Kling и др.)
    """
    try:
        # 1. Получаем путь к файлу в Telegram
        file = await bot.get_file(file_id)
        token = os.getenv("BOT_TOKEN")
        tg_url = f"https://api.telegram.org/file/bot{token}/{file.file_path}"

        async with aiohttp.ClientSession() as session:
            # 2. Скачиваем файл из Telegram
            async with session.get(tg_url) as resp:
                if resp.status != 200:
                    logging.error(f"❌ Не удалось скачать файл из Telegram: {resp.status}")
                    return tg_url

                file_data = await resp.read()

            # 3. Заливаем на Telegraph (самый быстрый и надежный вариант для нейросетей)
            form = aiohttp.FormData()
            # Telegraph требует имя файла и правильный mime-type
            form.add_field('file', file_data, filename='image.jpg', content_type='image/jpeg')

            async with session.post('https://telegra.ph/upload', data=form) as up_resp:
                if up_resp.status == 200:
                    result = await up_resp.json()
                    if isinstance(result, list) and len(result) > 0:
                        path = result[0].get('src')
                        res_url = f"https://telegra.ph{path}"
                        logging.info(f"✅ Фото успешно перезалито на Telegraph: {res_url}")
                        return res_url

                    logging.warning("⚠️ Telegraph вернул пустой список")
                    return tg_url
                else:
                    logging.warning(f"⚠️ Ошибка Telegraph ({up_resp.status}), используем прямую ссылку")
                    return tg_url

    except Exception as e:
        logging.error(f"❌ Ошибка в get_telegram_photo_url: {e}")
        # В случае критической ошибки пытаемся вернуть прямую ссылку на TG
        try:
            file = await bot.get_file(file_id)
            return f"https://api.telegram.org/file/bot{os.getenv('BOT_TOKEN')}/{file.file_path}"
        except:
            return ""