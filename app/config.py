import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Required fields
    bot_token: str
    polza_api_key: str

    # VK (optional)
    vk_token: str = ""
    vk_group_id: int = 0
    vk_disable_ssl_verify: bool = False
    vk_prodamus_url: str = "https://nano-banana-services.payform.ru"
    vk_prodamus_key: str = ""
    vk_webhook_port: int = 8444
    vk_admin_ids: tuple = ()

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Webhook / Payments
    webhook_port: int = 8443
    prodamus_key: str = os.getenv("PRODAMUS_KEY", "")


def get_settings() -> Settings:
    def env_bool(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    bot_token = os.getenv("BOT_TOKEN")
    polza_key = os.getenv("POLZA_API_KEY")
    vk_token = os.getenv("VK_TOKEN", "")
    vk_group_id = int(os.getenv("VK_GROUP_ID", 0))

    if not bot_token:
        raise RuntimeError("❌ BOT_TOKEN is missing in .env")
    if not polza_key:
        raise RuntimeError("❌ POLZA_API_KEY is missing in .env")

    return Settings(
        bot_token=bot_token,
        polza_api_key=polza_key,
        vk_token=vk_token,
        vk_group_id=vk_group_id,
        vk_disable_ssl_verify=env_bool("VK_DISABLE_SSL_VERIFY", False),
        vk_prodamus_url=os.getenv("VK_PRODAMUS_URL", "https://nano-banana-services.payform.ru"),
        vk_prodamus_key=os.getenv("VK_PRODAMUS_KEY", ""),
        vk_webhook_port=int(os.getenv("VK_WEBHOOK_PORT", 8444)),
        vk_admin_ids=tuple(
            int(x.strip()) for x in os.getenv("VK_ADMIN_IDS", "").split(",") if x.strip().isdigit()
        ),
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", 6379)),
        webhook_port=int(os.getenv("WEBHOOK_PORT", 8443))
    )


# Создаем объект настроек для импорта
settings = get_settings()