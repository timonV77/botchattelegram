from aiogram import Dispatcher

from .start import router as start_router
from .balance import router as balance_router
from .photo import router as photo_router
from .payments import router as payments_router
from .broadcast import router as broadcast_router


def setup_routers(dp: Dispatcher):
    # 1) Базовые команды
    dp.include_router(start_router)

    # 2) Баланс/платежи
    dp.include_router(balance_router)
    dp.include_router(payments_router)

    # 3) Основной пользовательский флоу
    dp.include_router(photo_router)

    # 4) Последним — broadcast (чтобы не перехватывал всё)
    dp.include_router(broadcast_router)