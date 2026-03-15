import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Telegram
    bot_token: str

    # API Polza (Kling, Nano Banana, Seedream)
    polza_api_key: str

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Webhook / Payments
    webhook_port: int = 8443
    prodamus_key: str = os.getenv("PRODAMUS_KEY", "")


def get_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN")
    polza_key = os.getenv("POLZA_API_KEY")

    if not bot_token:
        raise RuntimeError("❌ BOT_TOKEN is missing in .env")
    if not polza_key:
        raise RuntimeError("❌ POLZA_API_KEY is missing in .env")

    return Settings(
        bot_token=bot_token,
        polza_api_key=polza_key,
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", 6379)),
        webhook_port=int(os.getenv("WEBHOOK_PORT", 8443))
    )


# Создаем объект настроек для импорта
settings = get_settings()