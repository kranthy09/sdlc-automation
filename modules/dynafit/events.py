"""Generalized Redis event publishing for DYNAFIT phases.

Two-step publish strategy:
  1. persist_phase_state_sync — sync Redis hset (durable)
  2. publish_sync — sync Redis pub/sub (best-effort, live WebSocket)

Both use sync Redis so there are no event-loop conflicts
when called from Celery workers or LangGraph nodes.
"""

from __future__ import annotations

import asyncio
import os
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

REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379/0",
)

# -----------------------------------------------------------
# Async bridge — sync-to-async for terminal events
# -----------------------------------------------------------


def run_async(coro: Any) -> Any:
    """Run a coroutine from a synchronous context.

    Used by Phase 5 to publish terminal events
    (CompleteEvent) via async RedisPubSub.publish().
    """
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    except Exception as exc:
        log.warning(
            "run_async_failed",
            error=str(exc),
        )


# -----------------------------------------------------------
# Phase lifecycle events
# -----------------------------------------------------------


def publish_phase_start(
    batch_id: str,
    *,
    phase: int,
    phase_name: str,
) -> None:
    """Publish PhaseStartEvent. Non-fatal."""
    event = PhaseStartEvent(
        batch_id=batch_id,
        phase=phase,
        phase_name=phase_name,
    )
    _persist(event, batch_id, phase)
    _publish_sync(event, batch_id, phase)


def publish_phase_complete(
    batch_id: str,
    *,
    phase: int,
    phase_name: str,
    atoms_produced: int,
    atoms_validated: int,
    atoms_flagged: int,
    latency_ms: float,
) -> None:
    """Publish PhaseCompleteEvent. Non-fatal."""
    event = PhaseCompleteEvent(
        batch_id=batch_id,
        phase=phase,
        phase_name=phase_name,
        atoms_produced=atoms_produced,
        atoms_validated=atoms_validated,
        atoms_flagged=atoms_flagged,
        latency_ms=latency_ms,
    )
    _persist(event, batch_id, phase)
    _publish_sync(event, batch_id, phase)


def publish_step_progress(
    batch_id: str,
    *,
    phase: int,
    step: str,
    completed: int,
    total: int,
) -> None:
    """Publish StepProgressEvent. Non-fatal."""
    event = StepProgressEvent(
        batch_id=batch_id,
        phase=phase,
        step=step,
        completed=completed,
        total=total,
    )
    _persist(event, batch_id, phase)
    _publish_sync(event, batch_id, phase)


def publish_classification_event(
    batch_id: str,
    result: Any,
    *,
    journey: dict[str, Any] | None = None,
) -> None:
    """Publish ClassificationEvent with context. Non-fatal.

    When *journey* is provided the consultant can drill into
    evidence immediately from the live classification table.
    """
    d365_nav = ""
    if journey and journey.get("classify"):
        d365_nav = journey["classify"].get(
            "d365_navigation", ""
        )

    event = ClassificationEvent(
        batch_id=batch_id,
        atom_id=result.atom_id,
        classification=result.classification,
        confidence=result.confidence,
        requirement_text=result.requirement_text,
        module=result.module,
        rationale=result.rationale,
        d365_capability=(
            result.d365_capability_ref or ""
        ),
        d365_navigation=d365_nav,
        journey=journey,
    )
    _persist_classification(event, batch_id)
    _publish_sync(event, batch_id, phase=4)


# -----------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------


def _persist(
    event: Any,
    batch_id: str,
    phase: int,
) -> None:
    """Sync durable write to Redis hash."""
    try:
        RedisPubSub.persist_phase_state_sync(
            REDIS_URL,
            event,
        )
    except Exception as exc:
        log.warning(
            "redis_persist_failed",
            batch_id=batch_id,
            phase=phase,
            error=str(exc),
        )


def _persist_classification(
    event: ClassificationEvent,
    batch_id: str,
) -> None:
    """Append classification to durable Redis hash."""
    try:
        RedisPubSub.persist_classification_sync(
            REDIS_URL,
            event,
        )
    except Exception as exc:
        log.warning(
            "redis_classification_persist_failed",
            batch_id=batch_id,
            atom_id=event.atom_id,
            error=str(exc),
        )


def _publish_sync(
    event: Any,
    batch_id: str,
    phase: int,
) -> None:
    """Sync pub/sub publish via platform abstraction."""
    try:
        RedisPubSub.publish_sync(REDIS_URL, event)
    except Exception as exc:
        log.warning(
            "redis_pubsub_failed",
            batch_id=batch_id,
            phase=phase,
            error=str(exc),
        )
