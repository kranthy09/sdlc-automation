"""Generalized Redis event publishing for all DYNAFIT pipeline phases.

Consolidates the duplicated _publish_phase_event / _publish_phase_complete_event /
_publish_step_progress / _publish_classification_event helpers and the async bridge
that were copy-pasted across every node file.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from platform.observability.logger import get_logger
from platform.schemas.events import (
    ClassificationEvent,
    PhaseCompleteEvent,
    PhaseStartEvent,
    StepProgressEvent,
)
from platform.storage.redis_pub import RedisPubSub

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Async bridge — safe to call from sync or async contexts
# ---------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dynafit_events")


def run_async(coro: Any) -> Any:
    """Run a coroutine from a synchronous context.

    If an event loop is already running (e.g. inside graph.ainvoke()),
    submit the coroutine to a thread that owns a fresh event loop so we
    never block the caller's loop.
    """
    try:
        asyncio.get_running_loop()
        return _executor.submit(asyncio.run, coro).result(timeout=20)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Phase lifecycle events
# ---------------------------------------------------------------------------


def publish_phase_start(
    batch_id: str,
    redis: RedisPubSub | None,
    *,
    phase: int,
    phase_name: str,
) -> None:
    """Publish PhaseStartEvent. Non-fatal on failure."""
    if redis is None:
        return
    event = PhaseStartEvent(batch_id=batch_id, phase=phase, phase_name=phase_name)
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(redis.publish(event))
        finally:
            loop.close()
    except Exception as exc:
        log.warning("redis_publish_failed", batch_id=batch_id, phase=phase, error=str(exc))


def publish_phase_complete(
    batch_id: str,
    redis: RedisPubSub | None,
    *,
    phase: int,
    phase_name: str,
    atoms_produced: int,
    atoms_validated: int,
    atoms_flagged: int,
    latency_ms: float,
) -> None:
    """Publish PhaseCompleteEvent. Non-fatal on failure."""
    if redis is None:
        return
    event = PhaseCompleteEvent(
        batch_id=batch_id,
        phase=phase,
        phase_name=phase_name,
        atoms_produced=atoms_produced,
        atoms_validated=atoms_validated,
        atoms_flagged=atoms_flagged,
        latency_ms=latency_ms,
    )
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(redis.publish(event))
        finally:
            loop.close()
    except Exception as exc:
        log.warning("redis_publish_failed", batch_id=batch_id, phase=phase, error=str(exc))


def publish_step_progress(
    batch_id: str,
    redis: RedisPubSub | None,
    *,
    phase: int,
    step: str,
    completed: int,
    total: int,
) -> None:
    """Publish StepProgressEvent. Non-fatal on failure."""
    if redis is None:
        return
    event = StepProgressEvent(
        batch_id=batch_id,
        phase=phase,
        step=step,
        completed=completed,
        total=total,
    )
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(redis.publish(event))
        finally:
            loop.close()
    except Exception as exc:
        log.warning("redis_publish_failed", batch_id=batch_id, phase=phase, error=str(exc))


def publish_classification_event(
    batch_id: str,
    result: Any,
    redis: RedisPubSub | None,
) -> None:
    """Publish ClassificationEvent for one classified atom. Non-fatal on failure."""
    if redis is None:
        return
    event = ClassificationEvent(
        batch_id=batch_id,
        atom_id=result.atom_id,
        classification=result.classification,
        confidence=result.confidence,
    )
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(redis.publish(event))
        finally:
            loop.close()
    except Exception as exc:
        log.warning(
            "redis_publish_failed",
            batch_id=batch_id,
            atom_id=result.atom_id,
            error=str(exc),
        )
