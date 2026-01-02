from aiogram import Dispatcher

from .start import router as start_router
from .balance import router as balance_router
from .photo import router as photo_router
from .payments import router as payments_router


def setup_routers(dp: Dispatcher):
    # 1. Сначала системные команды (/start, помощь, отмена)
    dp.include_router(start_router)

    # 2. Профили и баланс
    dp.include_router(balance_router)

    # 3. Платежи (чтобы кнопки пополнения работали всегда)
    dp.include_router(payments_router)

    # 4. В самом конце — логика работы с фото и нейросетью
    # Так как этот роутер часто перехватывает "всё подряд"
    dp.include_router(photo_router)