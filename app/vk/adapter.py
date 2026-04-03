"""VK Bot Adapter - Minimal VK integration"""
import logging
from vkbottle.bot import Bot
from app.config import settings

logger = logging.getLogger(__name__)


class VKBotAdapter:
    """Wraps vkbottle Bot with our configuration"""

    def __init__(self):
        if not settings.vk_token:
            logger.warning("⚠️ VK_TOKEN not configured - VK bot disabled")
            self.bot = None
            return

        if not settings.vk_group_id:
            logger.warning("⚠️ VK_GROUP_ID not configured - VK bot disabled")
            self.bot = None
            return

        if settings.vk_disable_ssl_verify:
            self.bot = Bot(token=settings.vk_token)
            logger.warning("⚠️ VK SSL verification is disabled (VK_DISABLE_SSL_VERIFY=1)")
        else:
            self.bot = Bot(token=settings.vk_token)
        logger.info(f"✅ VK Bot initialized (Group ID: {settings.vk_group_id})")

    def is_enabled(self) -> bool:
        """Check if VK bot is enabled"""
        return self.bot is not None

    async def send_message(self, user_id: int, text: str, keyboard=None) -> bool:
        """Send message to VK user"""
        if not self.bot:
            return False

        try:
            await self.bot.api.messages.send(
                user_id=user_id,
                message=text,
                keyboard=keyboard,
                random_id=0
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send VK message to {user_id}: {e}")
            return False

    async def send_photo(self, user_id: int, photo_url: str, caption: str = "", keyboard=None) -> bool:
        """Send photo to VK user"""
        if not self.bot:
            return False

        try:
            # VK requires uploading photos differently
            # For now, send as file or message with link
            message = caption or "Photo generated"
            await self.bot.api.messages.send(
                user_id=user_id,
                message=message,
                keyboard=keyboard,
                random_id=0
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send VK photo to {user_id}: {e}")
            return False
