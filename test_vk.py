import logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

print("TEST: Step 1 - imports starting")
logger.info("TEST: Step 1 - Starting")

try:
    from app.config import settings
    logger.info(f"TEST: Config loaded, VK enabled: {bool(settings.vk_token)}")
except Exception as e:
    logger.error(f"TEST: Config error: {e}")

try:
    import vk_database as vk_db
    logger.info("TEST: vk_database imported")
except Exception as e:
    logger.error(f"TEST: vk_database error: {e}")

try:
    from app.vk.adapter import VKBotAdapter
    logger.info("TEST: VKBotAdapter imported")
    vk_bot = VKBotAdapter()
    logger.info(f"TEST: VK bot initialized, enabled: {vk_bot.is_enabled()}")
except Exception as e:
    logger.error(f"TEST: VK bot error: {e}")

logger.info("TEST: All imports successful!")
