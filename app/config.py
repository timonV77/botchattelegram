import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    bot_token: str
    payment_token: str

def get_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN", "")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is missing in .env")
    return Settings(
        bot_token=bot_token,
        payment_token=os.getenv("PAYMENT_TOKEN", "")
    )
