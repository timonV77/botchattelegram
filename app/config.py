import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Обязательные поля
    bot_token: str
    polza_api_key: str

    # Настройки базы данных (Telegram)
    db_name: str
    db_user: str
    db_pass: str
    db_host: str
    db_port: int

    # Настройки базы данных (VK)
    vk_db_name: str
    vk_db_user: str
    vk_db_pass: str
    vk_db_host: str
    vk_db_port: int

    # VK настройки
    vk_token: str = ""
    vk_group_id: int = 0
    vk_disable_ssl_verify: bool = False
    vk_prodamus_url: str = "https://nano-banana-services.payform.ru"
    vk_prodamus_key: str = ""
    vk_webhook_port: int = 8444
    vk_admin_ids: tuple = ()

    # Redis & Ports
    redis_host: str = "localhost"
    redis_port: int = 6379
    webhook_port: int = 8443
    prodamus_key: str = ""
    vk_user_token: str = ""


def get_settings() -> Settings:
    def env_bool(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    # Проверка критических ключей
    bot_token = os.getenv("BOT_TOKEN")
    polza_key = os.getenv("POLZA_API_KEY")

    if not bot_token or not polza_key:
        raise RuntimeError("❌ BOT_TOKEN or POLZA_API_KEY is missing in .env")

    return Settings(
        bot_token=bot_token,
        polza_api_key=polza_key,

        # Считываем переменные базы данных из .env (Telegram)
        db_name=os.getenv("DB_NAME", ""),
        db_user=os.getenv("DB_USER", ""),
        db_pass=os.getenv("DB_PASS", ""),
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("DB_PORT", 5432)),

        # Считываем переменные базы данных из .env (VK)
        vk_db_name=os.getenv("VK_DB_NAME", "bot_vk_db"),
        vk_db_user=os.getenv("VK_DB_USER", "bot_vk_user"),
        vk_db_pass=os.getenv("VK_DB_PASS", ""),
        vk_db_host=os.getenv("VK_DB_HOST", "127.0.0.1"),
        vk_db_port=int(os.getenv("VK_DB_PORT", 5432)),

        vk_token=os.getenv("VK_TOKEN", ""),
        vk_group_id=int(os.getenv("VK_GROUP_ID", 0)),
        vk_disable_ssl_verify=env_bool("VK_DISABLE_SSL_VERIFY", False),
        vk_prodamus_url=os.getenv("VK_PRODAMUS_URL", "https://nano-banana-services.payform.ru"),
        vk_prodamus_key=os.getenv("VK_PRODAMUS_KEY", ""),
        vk_webhook_port=int(os.getenv("VK_WEBHOOK_PORT", 8444)),
        vk_admin_ids=tuple(
            int(x.strip()) for x in os.getenv("VK_ADMIN_IDS", "").split(",") if x.strip().isdigit()
        ),
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", 6379)),
        webhook_port=int(os.getenv("WEBHOOK_PORT", 8443)),
        prodamus_key=os.getenv("PRODAMUS_KEY", ""),
        vk_user_token=os.getenv("VK_USER_TOKEN", "")
    )


settings = get_settings()