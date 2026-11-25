from dataclasses import dataclass
import json
import os
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class CategoryRule:
    name: str
    keywords: list[str]
    min_price: float
    max_price: float
    promo_ceiling: float


@dataclass(frozen=True)
class RulesConfig:
    min_discount_pct: int
    global_blacklist: list[str]
    categories: list[CategoryRule]


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_channel_id: str
    telegram_admin_chat_id: str

    enable_mercadolivre: bool
    enable_shopee: bool
    enable_amazon: bool

    ml_access_token: str
    ml_affiliate_param: str

    shopee_app_id: str
    shopee_app_secret: str

    amazon_access_key: str
    amazon_secret_key: str
    amazon_partner_tag: str

    poll_interval_minutes: int
    max_posts_per_cycle: int
    max_posts_per_day: int
    cooldown_days: int
    active_start_hour: int
    active_start_minute: int
    active_end_hour: int
    active_end_minute: int
    db_path: Path
    config_path: Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(env_file: str | None = None) -> Settings:
    load_dotenv(env_file)
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_channel_id=os.getenv("TELEGRAM_CHANNEL_ID", "").strip(),
        telegram_admin_chat_id=os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip(),
        enable_mercadolivre=_env_bool("ENABLE_MERCADOLIVRE", True),
        enable_shopee=_env_bool("ENABLE_SHOPEE", False),
        enable_amazon=_env_bool("ENABLE_AMAZON", False),
        ml_access_token=os.getenv("ML_ACCESS_TOKEN", "").strip(),
        ml_affiliate_param=os.getenv("ML_AFFILIATE_PARAM", "").strip(),
        shopee_app_id=os.getenv("SHOPEE_APP_ID", "").strip(),
        shopee_app_secret=os.getenv("SHOPEE_APP_SECRET", "").strip(),
        amazon_access_key=os.getenv("AMAZON_ACCESS_KEY", "").strip(),
        amazon_secret_key=os.getenv("AMAZON_SECRET_KEY", "").strip(),
        amazon_partner_tag=os.getenv("AMAZON_PARTNER_TAG", "").strip(),
        poll_interval_minutes=int(os.getenv("POLL_INTERVAL_MINUTES", "20")),
        max_posts_per_cycle=int(os.getenv("MAX_POSTS_PER_CYCLE", "2")),
        max_posts_per_day=int(os.getenv("MAX_POSTS_PER_DAY", "15")),
        cooldown_days=int(os.getenv("COOLDOWN_DAYS", "7")),
        active_start_hour=int(os.getenv("ACTIVE_START_HOUR", "7")),
        active_start_minute=int(os.getenv("ACTIVE_START_MINUTE", "30")),
        active_end_hour=int(os.getenv("ACTIVE_END_HOUR", "22")),
        active_end_minute=int(os.getenv("ACTIVE_END_MINUTE", "30")),
        db_path=Path(os.getenv("DB_PATH", "data/bot.db")),
        config_path=Path(os.getenv("CONFIG_PATH", "config/futevolei.json")),
    )


def load_rules(path: Path) -> RulesConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    categories = [
        CategoryRule(
            name=c["name"],
            keywords=c["keywords"],
            min_price=float(c["min_price"]),
            max_price=float(c["max_price"]),
            promo_ceiling=float(c["promo_ceiling"]),
        )
        for c in data["categories"]
    ]
    return RulesConfig(
        min_discount_pct=int(data["min_discount_pct"]),
        global_blacklist=list(data["global_blacklist"]),
        categories=categories,
    )
