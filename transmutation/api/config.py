"""Configuration loader"""
# go to .env to modify configuration variables or use environment variables
from logging import DEBUG
from typing import Optional
from requests import get
from requests.exceptions import ConnectionError
from random import choice

from loguru import logger as log

from redis.asyncio import Redis
from pydantic_settings import BaseSettings, SettingsConfigDict

NITTER_INSTANCES = "https://status.d420.de/api/v1/instances"
NITTER_BACKUP_INSTANCE = "https://nitter.net"


def pick_nitter_instance(
    instances_url=NITTER_INSTANCES, backup_instance=NITTER_BACKUP_INSTANCE, timeout=3, min_points=50
) -> str:
    instance = ""
    try:
        instances = {
            instance["ping_avg"]: instance["url"]
            for instance in get(instances_url, timeout=timeout).json()["hosts"]
            if instance["points"] > min_points
        }
        instance = instances[choice(sorted(instances.keys())[:5])]
    except ConnectionError:
        instance = backup_instance
    return instance


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
    public_email_providers_url: str = (
        "https://raw.githubusercontent.com/ankaboot-source/email-open-data/main/public-email-providers.json"
    )
    public_email_providers: Optional[set[str]] = None
    persons_bulk_max: int = 10000
    jobtitles_list_file: str = "miners/jobtitles.json"
    model_config = SettingsConfigDict(env_file=".env")
    nitter_instance_server: str = pick_nitter_instance()


settings = Settings()

if not settings.public_email_providers:
    try:
        public_email_providers = get(settings.public_email_providers_url).json()
        settings.public_email_providers = set(public_email_providers)
    except ConnectionError as e:
        log.info(f"Impossible to GET public_email_providers_url: {e}")


# build connection string for redis
redis_credentials = ""
if settings.redis_username:
    redis_credentials += settings.redis_username
    if settings.redis_password:
        redis_credentials += f":{settings.redis_password}"
    redis_credentials += "@"
redis_url = f"redis://{redis_credentials}{settings.redis_host}:{settings.redis_port}"


async def setup_cache(settings: Settings, db: int) -> Redis:
    """setup cache based on Redis

    Args:
        settings (Settings):settings including redis_*
        db (str): database name

    Returns:
        redis: redis database instance
    """
    # redis parameters
    redis_parameters = {
        setting_k.removeprefix("redis_"): setting_v
        for setting_k, setting_v in settings.dict().items()
        if setting_k.startswith("redis")
    }
    redis_parameters["db"] = db
    redis_parameters["decode_responses"] = True
    redis_parameters["encoding"] = "utf-8"
    cache = await Redis(**redis_parameters)
    log.info(f"Set-up redis cache for {db}")
    return cache


# celery broker & backend based on redis
celery_backend = celery_broker = "{redis_url}/{settings.celery_redis_db}"
