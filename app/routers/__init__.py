from aiogram import Dispatcher

from .start import router as start_router
from .balance import router as balance_router
from .photo import router as photo_router
from .payments import router as payments_router


def setup_routers(dp: Dispatcher):
    dp.include_router(start_router)
    dp.include_router(balance_router)
    dp.include_router(photo_router)
    dp.include_router(payments_router)
