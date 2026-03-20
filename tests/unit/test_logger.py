"""
TDD — platform/observability/logger.py

Tests use structlog.testing.capture_logs() to inspect log events as dicts
without requiring a real output stream or a configured structlog pipeline.
correlation_id is tested via structlog.contextvars.get_contextvars() directly,
which is independent of the renderer/processor chain.
"""

import pytest
import structlog.contextvars
from structlog.testing import capture_logs

# ---------------------------------------------------------------------------
# Fixture — clear contextvars between tests to prevent state leak
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_ctx() -> None:
    """Ensure no stale contextvars bleed across tests."""
    structlog.contextvars.clear_contextvars()


# ---------------------------------------------------------------------------
# Capturing log events
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_log_captures_event() -> None:
    """Log calls produce entries with the correct event and fields."""
    from platform.observability.logger import get_logger

    with capture_logs() as logs:
        log = get_logger("test")
        log.info("request_received", path="/health", method="GET")

    assert len(logs) == 1
    assert logs[0]["event"] == "request_received"
    assert logs[0]["path"] == "/health"
    assert logs[0]["method"] == "GET"
    assert logs[0]["log_level"] == "info"


@pytest.mark.unit
def test_log_captures_multiple_levels() -> None:
    """info, warning, and error are all captured correctly."""
    from platform.observability.logger import get_logger

    with capture_logs() as logs:
        log = get_logger("test")
        log.info("info_msg")
        log.warning("warn_msg")
        log.error("error_msg")

    assert len(logs) == 3
    assert [e["log_level"] for e in logs] == ["info", "warning", "error"]


@pytest.mark.unit
def test_log_captures_extra_kwargs() -> None:
    """Keyword arguments are stored as fields on the log event."""
    from platform.observability.logger import get_logger

    with capture_logs() as logs:
        log = get_logger("test")
        log.info("atom_processed", atom_id="REQ-001", score=0.92)

    assert logs[0]["atom_id"] == "REQ-001"
    assert logs[0]["score"] == 0.92


# ---------------------------------------------------------------------------
# correlation_id via contextvars
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bind_correlation_id_sets_context() -> None:
    """bind_correlation_id() stores the id in structlog contextvars."""
    from platform.observability.logger import bind_correlation_id

    bind_correlation_id("corr-abc-123")

    ctx = structlog.contextvars.get_contextvars()
    assert ctx["correlation_id"] == "corr-abc-123"


@pytest.mark.unit
def test_clear_correlation_id_removes_context() -> None:
    """clear_correlation_id() removes correlation_id from contextvars."""
    from platform.observability.logger import bind_correlation_id, clear_correlation_id

    bind_correlation_id("corr-to-remove")
    clear_correlation_id()

    ctx = structlog.contextvars.get_contextvars()
    assert "correlation_id" not in ctx


@pytest.mark.unit
def test_bind_correlation_id_overwrites_previous() -> None:
    """Calling bind_correlation_id twice keeps the latest value."""
    from platform.observability.logger import bind_correlation_id

    bind_correlation_id("first-id")
    bind_correlation_id("second-id")

    ctx = structlog.contextvars.get_contextvars()
    assert ctx["correlation_id"] == "second-id"


@pytest.mark.unit
def test_correlation_id_merged_into_event_dict() -> None:
    """correlation_id bound via bind_correlation_id is merged into log event dicts.

    capture_logs() bypasses the processor chain (it replaces all processors with
    a bare capture sink), so merge_contextvars never runs inside capture_logs().
    Instead, we invoke the processor directly — this is exactly what structlog
    calls for every log record when the real pipeline runs.
    """
    from platform.observability.logger import bind_correlation_id

    bind_correlation_id("trace-xyz")

    # Simulate what configure_logging's merge_contextvars processor does.
    event_dict: dict[str, object] = {"event": "traced_call"}
    result = structlog.contextvars.merge_contextvars(None, "info", event_dict)

    assert isinstance(result, dict)
    assert result["correlation_id"] == "trace-xyz"


@pytest.mark.unit
def test_no_correlation_id_when_not_bound() -> None:
    """No correlation_id field when bind_correlation_id was not called."""
    from platform.observability.logger import get_logger

    with capture_logs() as logs:
        log = get_logger("test")
        log.info("untraced_call")

    assert "correlation_id" not in logs[0]


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_configure_logging_runs_without_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """configure_logging() completes without raising."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    from platform.config.settings import get_settings

    get_settings.cache_clear()
    try:
        from platform.observability.logger import configure_logging

        configure_logging()  # must not raise
    finally:
        get_settings.cache_clear()


@pytest.mark.unit
def test_configure_logging_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
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
        configure_logging()  # second call must not raise or corrupt state
    finally:
        get_settings.cache_clear()


