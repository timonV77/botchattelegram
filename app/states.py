from aiogram.fsm.state import State, StatesGroup


class PhotoProcess(StatesGroup):
    # Состояния для обычной фотосессии (Image-to-Image)
    waiting_for_photo = State()
    waiting_for_model = State()
    waiting_for_prompt = State()

    # Состояния для оживления фото (Kling 2.5)
    waiting_for_video_photo = State()  # Ожидание фото для видео
    waiting_for_duration = State()  # Выбор 5 или 10 секунд
    waiting_for_video_prompt = State()  # Описание движения

    # Состояния для Motion Control (Kling v2.6)
    waiting_for_motion_video = State()  # Ожидание видео с движением
    waiting_for_motion_mode = State()  # Выбор режима (720p/1080p)
    waiting_for_motion_orientation = State()  # Выбор ориентации (image/video)