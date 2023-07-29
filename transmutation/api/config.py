"""Configuration loader"""
# go to .env to modify configuration variables or use environment variables
from logging import DEBUG
from typing import Optional
from requests import get
from requests.exceptions import ConnectionError

from loguru import logger as log

from redis import Redis
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Transmutation API"
    google_api_key: str
    google_cx: str
    google_vision_credentials: str
    query_type: str = "q"
    bing_api_key: Optional[str] = None
    bing_customconfig: Optional[str] = None
    log_level: Optional[int] = DEBUG
    log_file: Optional[str] = None
    redis_username: Optional[str] = None
    redis_password: Optional[str] = None
    redis_host: str
    redis_port: str
    cache_redis_db: int
    cache_expiration: int
    celery_redis_db: int
    server_port: int
    api_keys: list[str]
    api_key_name: str
    bulk_size: int
    google_vision_credentials: str
    public_email_providers_url: str = "https://raw.githubusercontent.com/ankaboot-source/email-open-data/main/public-email-providers.json"
    public_email_providers: Optional[set[str]] = None
    persons_bulk_max: int = 10000
    jobtitles_list_file: str = "miners/jobtitles.json"
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()

if not settings.public_email_providers:
    try:
        public_email_providers = get(
            settings.public_email_providers_url).json()
        settings.public_email_providers = set(public_email_providers)
    except ConnectionError as e:
        log.info(f"Impossible to GET public_email_providers_url: {e}")


def setup_cache(settings: Settings, db: int) -> Redis:
    """setup cache based on Redis

    Args:
        settings (Settings):settings including redis_*
        db (str): database name

    Returns:
        Redis: redis database instance
    """
    # redis parameters
    redis_parameters = {
        setting_k.removeprefix("redis_"): setting_v
        for setting_k, setting_v in settings.dict().items()
        if setting_k.startswith("redis")
    }
    redis_parameters["db"] = db
    redis_parameters["decode_responses"] = True
    cache = Redis(**redis_parameters)
    log.info(f"Set-up Redis cache for {db}")
    return cache


# build connection string for redis
redis_credentials = ""
if settings.redis_username:
    redis_credentials += settings.redis_username
    if settings.redis_password:
        redis_credentials += f":{settings.redis_password}"
    redis_credentials += "@"

# celery broker & backend based on redis
celery_backend = (
    celery_broker
) = f"redis://{redis_credentials}{settings.redis_host}:{settings.redis_port}/{settings.celery_redis_db}"
