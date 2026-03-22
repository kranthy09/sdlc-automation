"""
TDD — platform/observability/logger.py

Core behaviours: log capture, correlation_id bind/clear, configure_logging.
"""

import pytest
import structlog.contextvars
from structlog.testing import capture_logs


@pytest.fixture(autouse=True)
def clear_ctx() -> None:
    """Ensure no stale contextvars bleed across tests."""
    structlog.contextvars.clear_contextvars()


@pytest.mark.unit
def test_log_captures_event_with_fields() -> None:
    """Log calls produce entries with the correct event, level, and fields."""
    from platform.observability.logger import get_logger

    with capture_logs() as logs:
        log = get_logger("test")
        log.info("request_received", path="/health", method="GET")

    assert len(logs) == 1
    assert logs[0]["event"] == "request_received"
    assert logs[0]["path"] == "/health"
    assert logs[0]["log_level"] == "info"


@pytest.mark.unit
def test_bind_and_clear_correlation_id() -> None:
    """bind_correlation_id sets contextvar; clear removes it."""
    from platform.observability.logger import (
        bind_correlation_id,
        clear_correlation_id,
    )

    bind_correlation_id("corr-abc-123")
    ctx = structlog.contextvars.get_contextvars()
    assert ctx["correlation_id"] == "corr-abc-123"

    clear_correlation_id()
    ctx = structlog.contextvars.get_contextvars()
    assert "correlation_id" not in ctx


@pytest.mark.unit
def test_correlation_id_merged_into_event_dict() -> None:
    """correlation_id bound via bind_correlation_id is merged into log events."""
    from platform.observability.logger import bind_correlation_id

    bind_correlation_id("trace-xyz")

    event_dict: dict[str, object] = {"event": "traced_call"}
    result = structlog.contextvars.merge_contextvars(
        None, "info", event_dict,
    )

    assert isinstance(result, dict)
    assert result["correlation_id"] == "trace-xyz"


@pytest.mark.unit
def test_configure_logging_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_logging() can be called multiple times without error."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    from platform.config.settings import get_settings

    get_settings.cache_clear()
    try:
        from platform.observability.logger import configure_logging

        configure_logging()
        configure_logging()  # second call must not raise
    finally:
        get_settings.cache_clear()
