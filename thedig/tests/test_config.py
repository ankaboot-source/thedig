"""Tests for the Settings proxy fallback behaviour."""

from thedig.api.config import Settings

BASE_KWARGS = {
    "api_keys": ["k"],
    "api_key_name": "X-API-KEY",
    "redis_host": "localhost",
    "redis_port": "6379",
}


def make_settings(**overrides) -> Settings:
    # isolate from the local .env so the assertions are deterministic
    return Settings(_env_file=None, **BASE_KWARGS, **overrides)


def test_explicit_proxy_wins_over_https_and_http_proxy():
    settings = make_settings(
        proxy="http://explicit:8080", https_proxy="http://https:8080", http_proxy="http://http:8080"
    )

    assert settings.proxy == "http://explicit:8080"


def test_https_proxy_backfills_proxy_and_wins_over_http_proxy():
    settings = make_settings(https_proxy="http://https:8080", http_proxy="http://http:8080")

    assert settings.proxy == "http://https:8080"


def test_http_proxy_backfills_proxy_when_https_proxy_missing():
    settings = make_settings(http_proxy="http://http:8080")

    assert settings.proxy == "http://http:8080"


def test_proxy_stays_none_without_any_proxy_setting():
    settings = make_settings()

    assert settings.proxy is None
