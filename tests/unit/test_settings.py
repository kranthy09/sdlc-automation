"""
TDD — platform/config/settings.py

Core behaviours: loads from env, validates required fields, singleton caching.
"""

import pytest


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv(
        "POSTGRES_URL", "postgresql+asyncpg://user:pw@localhost/testdb",
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")


@pytest.mark.unit
def test_settings_load_and_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings loads with all required env vars and has correct defaults."""
    _set_required_env(monkeypatch)

    from platform.config.settings import Settings

    s = Settings()
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-test-key"
    assert s.environment == "development"
    assert s.log_level == "INFO"
    assert s.default_llm_model == "claude-sonnet-4-6"


@pytest.mark.unit
def test_settings_missing_api_key_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing ANTHROPIC_API_KEY raises a validation error."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv(
        "POSTGRES_URL", "postgresql+asyncpg://user:pw@localhost/testdb",
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    from pydantic import ValidationError

    from platform.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.unit
def test_get_settings_returns_same_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_settings() returns the same cached instance on repeated calls."""
    _set_required_env(monkeypatch)

    from platform.config.settings import get_settings

    get_settings.cache_clear()

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2

    get_settings.cache_clear()
