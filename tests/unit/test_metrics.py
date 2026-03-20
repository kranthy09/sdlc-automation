"""
TDD — platform/observability/metrics.py

Tests use an isolated CollectorRegistry per test to avoid pollution
of the global prometheus_client REGISTRY and prevent "already registered"
errors across test runs.
"""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample(registry: CollectorRegistry, sample_name: str, labels: dict[str, str]) -> float:
    """Return the value for a specific sample name + label set from a registry.

    Iterates all collected samples so it works regardless of how prometheus_client
    maps metric family names to sample names (e.g. Counter appends ``_total``).
    """
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == sample_name and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# record_call — success path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_call_increments_ok_counter_on_success() -> None:
    """Successful call increments platform_external_calls_total with status=ok."""
    from platform.observability.metrics import MetricsRecorder

    registry = CollectorRegistry()
    recorder = MetricsRecorder(registry=registry)

    with recorder.record_call("llm", "invoke"):
        pass

    value = _sample(
        registry,
        "platform_external_calls_total",
        {"service": "llm", "operation": "invoke", "status": "ok"},
    )
    assert value == 1.0


@pytest.mark.unit
def test_record_call_records_duration_on_success() -> None:
    """Successful call records a non-negative observation in the histogram."""
    from platform.observability.metrics import MetricsRecorder

    registry = CollectorRegistry()
    recorder = MetricsRecorder(registry=registry)

    with recorder.record_call("qdrant", "search"):
        pass

    # Histogram _count should be 1 after one observation
    count = _sample(
        registry,
        "platform_external_call_duration_seconds_count",
        {"service": "qdrant", "operation": "search"},
    )
    assert count == 1.0


@pytest.mark.unit
def test_record_call_multiple_calls_accumulate() -> None:
    """Multiple calls to the same (service, operation) accumulate in the counter."""
    from platform.observability.metrics import MetricsRecorder

    registry = CollectorRegistry()
    recorder = MetricsRecorder(registry=registry)

    for _ in range(3):
        with recorder.record_call("postgres", "query"):
            pass

    value = _sample(
        registry,
        "platform_external_calls_total",
        {"service": "postgres", "operation": "query", "status": "ok"},
    )
    assert value == 3.0


# ---------------------------------------------------------------------------
# record_call — error path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_call_increments_error_counter_on_exception() -> None:
    """Exception inside record_call increments counter with status=error."""
    from platform.observability.metrics import MetricsRecorder

    registry = CollectorRegistry()
    recorder = MetricsRecorder(registry=registry)

    with pytest.raises(RuntimeError):
        with recorder.record_call("redis", "publish"):
            raise RuntimeError("connection refused")

    value = _sample(
        registry,
        "platform_external_calls_total",
        {"service": "redis", "operation": "publish", "status": "error"},
    )
    assert value == 1.0


@pytest.mark.unit
def test_record_call_does_not_increment_ok_on_exception() -> None:
    """Exception inside record_call must NOT increment the ok counter."""
    from platform.observability.metrics import MetricsRecorder

    registry = CollectorRegistry()
    recorder = MetricsRecorder(registry=registry)

    with pytest.raises(ValueError):
        with recorder.record_call("llm", "invoke"):
            raise ValueError("bad payload")

    ok_value = _sample(
        registry,
        "platform_external_calls_total",
        {"service": "llm", "operation": "invoke", "status": "ok"},
    )
    assert ok_value == 0.0


@pytest.mark.unit
def test_record_call_records_duration_even_on_exception() -> None:
    """Duration is recorded regardless of whether the call succeeded or failed."""
    from platform.observability.metrics import MetricsRecorder

    registry = CollectorRegistry()
    recorder = MetricsRecorder(registry=registry)

    with pytest.raises(IOError):
        with recorder.record_call("qdrant", "upsert"):
            raise OSError("timeout")

    count = _sample(
        registry,
        "platform_external_call_duration_seconds_count",
        {"service": "qdrant", "operation": "upsert"},
    )
    assert count == 1.0


@pytest.mark.unit
def test_record_call_reraises_exception() -> None:
    """record_call must re-raise the original exception unchanged."""
    from platform.observability.metrics import MetricsRecorder

    registry = CollectorRegistry()
    recorder = MetricsRecorder(registry=registry)

    original = ValueError("original error")
    with pytest.raises(ValueError) as exc_info:
        with recorder.record_call("llm", "invoke"):
            raise original

    assert exc_info.value is original


# ---------------------------------------------------------------------------
# Multiple services share the same recorder without collision
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_different_services_tracked_independently() -> None:
    """Calls for different services are stored under distinct label sets."""
    from platform.observability.metrics import MetricsRecorder

    registry = CollectorRegistry()
    recorder = MetricsRecorder(registry=registry)

    with recorder.record_call("llm", "invoke"):
        pass

    with pytest.raises(RuntimeError):
        with recorder.record_call("postgres", "query"):
            raise RuntimeError("db down")

    llm_ok = _sample(
        registry,
        "platform_external_calls_total",
        {"service": "llm", "operation": "invoke", "status": "ok"},
    )
    pg_error = _sample(
        registry,
        "platform_external_calls_total",
        {"service": "postgres", "operation": "query", "status": "error"},
    )
    assert llm_ok == 1.0
    assert pg_error == 1.0


