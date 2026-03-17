import logging
from aiogram import Dispatcher

from .start import router as start_router
from .balance import router as balance_router
from .users_count import router as users_count_router
from .photo import router as photo_router
from .payments import router as payments_router
from .broadcast import router as broadcast_router


def setup_routers(dp: Dispatcher):
    logging.info("SETUP_ROUTERS CALLED")
    dp.include_router(start_router)
    dp.include_router(balance_router)
    dp.include_router(users_count_router)
    dp.include_router(payments_router)
    dp.include_router(photo_router)
    dp.include_router(broadcast_router)
    logging.info("SETUP_ROUTERS DONE")