"""Configuration loader"""
# go to .env to modify configuration variables or use environment variables
from logging import DEBUG
from typing import Optional

from pydantic import BaseSettings
from requests import get
from requests.exceptions import ConnectionError

from loguru import logger as log


class Settings(BaseSettings):
    app_name: str = "Transmutation API"
    google_api_key: str
    google_cx: str
    google_vision_credentials: str
    query_type: str = "q"
    bing_api_key: str | None
    bing_customconfig: str | None
    log_level: Optional[int] = DEBUG
    log_file: str | None
    redis_username: Optional[str]
    redis_password: Optional[str]
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
    public_email_providers_url: str
    public_email_providers: Optional[set[str]]
    persons_bulk_max: int = 10000

    class Config:
        env_file = ".env"


settings = Settings()

if not settings.public_email_providers:
    try:
        public_email_providers = get(
            settings.public_email_providers_url).json()
        settings.public_email_providers = set(public_email_providers)
    except ConnectionError as e:
        log.info(f"Impossible to GET public_email_providers_url: {e}")

# redis parameters
redis_parameters = {
    setting_k.removeprefix("redis_"): setting_v
    for setting_k, setting_v in settings.dict().items()
    if setting_k.startswith("redis")
}

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
