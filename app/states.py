from aiogram.fsm.state import State, StatesGroup

class PhotoProcess(StatesGroup):
    waiting_for_photo = State()
    waiting_for_model = State()
    waiting_for_prompt = State()
