"""
Prometheus metrics for every external call made by the platform.

Design rules (enforced here, nowhere else):
  - One Counter and one Histogram cover all external services.
  - Labels identify the service (llm | qdrant | postgres | redis) and
    the operation (e.g. invoke, search, query, publish).
  - record_call() is the single entry point — context manager that
    times the call, increments ok/error, and always re-raises.
  - MetricsRecorder accepts an optional registry for test isolation.
  - Module-level record_call() delegates to the default recorder which
    uses prometheus_client's global REGISTRY.

Usage:
    # In platform/llm/client.py, platform/storage/postgres.py, etc.:
    from platform.observability.metrics import record_call

    with record_call("llm", "invoke"):
        response = anthropic_client.messages.create(...)

    with record_call("postgres", "query"):
        result = await session.execute(stmt)
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager

from prometheus_client import REGISTRY as _DEFAULT_REGISTRY
from prometheus_client import CollectorRegistry, Counter, Histogram


class MetricsRecorder:
    """Holds Prometheus instruments and provides a recording context manager.

    Args:
        registry: CollectorRegistry to register metrics against.
                  Defaults to the global prometheus_client REGISTRY.
                  Pass a fresh CollectorRegistry() in tests for isolation.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        _registry = registry if registry is not None else _DEFAULT_REGISTRY

        self._call_total = Counter(
            "platform_external_calls_total",
            "Total external calls by service, operation, and outcome",
            ["service", "operation", "status"],
            registry=_registry,
        )
        self._call_duration = Histogram(
            "platform_external_call_duration_seconds",
            "Latency of external calls in seconds",
            ["service", "operation"],
            registry=_registry,
        )

    @contextmanager
    def record_call(self, service: str, operation: str) -> Generator[None, None, None]:
        """Time a single external call and record its outcome.

        Increments ``platform_external_calls_total`` with ``status="ok"``
        on success or ``status="error"`` on any exception, and always
        records the elapsed time in ``platform_external_call_duration_seconds``.
        Exceptions are re-raised unchanged.

        Args:
            service:   Infra target — "llm", "qdrant", "postgres", "redis".
            operation: Verb describing the call — "invoke", "search", "query", etc.
        """
        start = time.perf_counter()
        try:
            yield
        except Exception:
            self._call_total.labels(service=service, operation=operation, status="error").inc()
            raise
        else:
            self._call_total.labels(service=service, operation=operation, status="ok").inc()
        finally:
            elapsed = time.perf_counter() - start
            self._call_duration.labels(service=service, operation=operation).observe(elapsed)


# ---------------------------------------------------------------------------
# Module-level default recorder and convenience function
# ---------------------------------------------------------------------------

_recorder = MetricsRecorder()

record_call = _recorder.record_call
