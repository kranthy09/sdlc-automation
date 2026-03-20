"""
TDD — platform/config/settings.py

RED: all tests fail before implementation exists.
GREEN: implement Settings to pass these tests.
"""

import pytest

# ---------------------------------------------------------------------------
# Happy-path defaults
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_settings_load_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings loads successfully when all required env vars are present."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://user:pw@localhost/testdb")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    # Import inside test to respect monkeypatched env
    from platform.config.settings import Settings

    s = Settings()
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-test-key"
    assert s.postgres_url == "postgresql+asyncpg://user:pw@localhost/testdb"
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.qdrant_url == "http://localhost:6333"


@pytest.mark.unit
def test_settings_default_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional fields have correct defaults."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://user:pw@localhost/testdb")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    from platform.config.settings import Settings

    s = Settings()
    assert s.environment == "development"
    assert s.log_level == "INFO"
    assert s.default_llm_model == "claude-sonnet-4-6"


@pytest.mark.unit
def test_settings_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment and log_level can be overridden via env vars."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://user:pw@localhost/testdb")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    from platform.config.settings import Settings

    s = Settings()
    assert s.environment == "production"
    assert s.log_level == "WARNING"


# ---------------------------------------------------------------------------
# Validation — required fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_settings_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing ANTHROPIC_API_KEY raises a validation error."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://user:pw@localhost/testdb")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    from pydantic import ValidationError

    from platform.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.unit
def test_settings_missing_postgres_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing POSTGRES_URL raises a validation error."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    from pydantic import ValidationError

    from platform.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings()


# ---------------------------------------------------------------------------
# Validation — allowed literal values
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_settings_invalid_environment_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised ENVIRONMENT value raises a validation error."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://user:pw@localhost/testdb")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("ENVIRONMENT", "local")  # not in allowed set

    from pydantic import ValidationError

    from platform.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.unit
def test_settings_invalid_log_level_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised LOG_LEVEL value raises a validation error."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://user:pw@localhost/testdb")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("LOG_LEVEL", "TRACE")  # not in allowed set

    from pydantic import ValidationError

    from platform.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings()


# ---------------------------------------------------------------------------
# get_settings() — cached singleton
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_settings_returns_same_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_settings() returns the same cached instance on repeated calls."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://user:pw@localhost/testdb")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    from platform.config.settings import get_settings

    # Clear the cache so monkeypatched env is picked up
    get_settings.cache_clear()

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2

    get_settings.cache_clear()
