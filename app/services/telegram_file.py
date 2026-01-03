import os
import aiohttp
import logging
from aiogram import Bot


async def get_telegram_photo_url(bot: Bot, file_id: str) -> str:
    """
    Скачивает фото из Telegram и перезаливает его на временный хостинг,
    чтобы не светить TOKEN и обойти блокировки api.telegram.org
    """
    try:
        # 1. Получаем путь к файлу
        file = await bot.get_file(file_id)
        token = os.getenv("BOT_TOKEN")
        tg_url = f"https://api.telegram.org/file/bot{token}/{file.file_path}"

        # 2. Скачиваем файл во временный буфер и заливаем на Catbox (или аналог)
        # Это бесплатный анонимный хостинг, который отлично едят все нейросети
        async with aiohttp.ClientSession() as session:
            # Сначала скачиваем из телеги
            async with session.get(tg_url) as resp:
                if resp.status != 200:
                    logging.error(f"❌ Не удалось скачать файл из Telegram: {resp.status}")
                    return tg_url  # запасной вариант

                file_data = await resp.read()

            # Теперь заливаем на Catbox.moe
            data = aiohttp.FormData()
            data.add_field('reqtype', 'fileupload')
            data.add_field('fileToUpload', file_data, filename='image.jpg')

            async with session.post('https://catbox.moe/user/api.php', data=data) as up_resp:
                if up_resp.status == 200:
                    res_url = await up_resp.text()
                    logging.info(f"✅ Фото успешно перезалито: {res_url.strip()}")
                    return res_url.strip()
                else:
                    logging.warning(f"⚠️ Ошибка перезаливки на хостинг, используем прямую ссылку")
                    return tg_url

    except Exception as e:
        logging.error(f"❌ Ошибка в get_telegram_photo_url: {e}")
        # Если всё упало, возвращаем хотя бы прямую ссылку (как было)
        return f"https://api.telegram.org/file/bot{os.getenv('BOT_TOKEN')}/{file.file_path}"