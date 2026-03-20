"""
Platform-wide configuration via environment variables.

All infrastructure coordinates and tuneable parameters live here.
No other module may hardcode URLs, model names, or credentials.

Usage:
    from platform.config.settings import get_settings

    s = get_settings()
    print(s.postgres_url)

Loading order (pydantic-settings):
    1. Environment variables (highest priority)
    2. .env file in the working directory (if present)
    3. Field defaults (lowest priority)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Runtime environment
    # ------------------------------------------------------------------
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------
    anthropic_api_key: SecretStr

    # ------------------------------------------------------------------
    # Infrastructure — connection URLs
    # ------------------------------------------------------------------
    postgres_url: str  # e.g. postgresql+asyncpg://user:pw@host/db
    redis_url: str  # e.g. redis://localhost:6379/0
    qdrant_url: str  # e.g. http://localhost:6333

    # ------------------------------------------------------------------
    # AI model defaults (overridden per-product via ProductConfig)
    # ------------------------------------------------------------------
    default_llm_model: str = "claude-sonnet-4-6"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached platform Settings instance.

    Call get_settings.cache_clear() in tests that monkeypatch env vars.
    """
    return Settings()
