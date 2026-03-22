"""Generalized Redis event publishing for DYNAFIT phases.

Two-step publish strategy:
  1. persist_phase_state_sync — sync Redis hset (durable)
  2. redis pub/sub — async (best-effort, live WebSocket)

Step 1 uses sync Redis so there are no event-loop conflicts
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
    redis: RedisPubSub | None,
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
    if redis is not None:
        _publish_async(redis, event, batch_id, phase)


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
    if redis is not None:
        _publish_async(redis, event, batch_id, phase)


def publish_step_progress(
    batch_id: str,
    redis: RedisPubSub | None,
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
    if redis is not None:
        _publish_async(redis, event, batch_id, phase)


def publish_classification_event(
    batch_id: str,
    result: Any,
    redis: RedisPubSub | None,
) -> None:
    """Publish ClassificationEvent. Non-fatal."""
    event = ClassificationEvent(
        batch_id=batch_id,
        atom_id=result.atom_id,
        classification=result.classification,
        confidence=result.confidence,
    )
    _persist_classification(event, batch_id)
    if redis is not None:
        _publish_async(redis, event, batch_id, phase=4)


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
    import json  # noqa: PLC0415

    import redis as sync_redis  # noqa: PLC0415

    hash_key = f"batch:{batch_id}"
    entry = {
        "atom_id": event.atom_id,
        "classification": event.classification,
        "confidence": event.confidence,
    }
    try:
        r = sync_redis.from_url(REDIS_URL)
        try:
            raw = r.hget(hash_key, "classifications")
            rows: list[dict[str, Any]] = json.loads(raw) if raw else []
        except Exception:
            rows = []
        # Deduplicate by atom_id
        if not any(x["atom_id"] == event.atom_id for x in rows):
            rows.append(entry)
            r.hset(
                hash_key,
                "classifications",
                json.dumps(rows),
            )
    except Exception as exc:
        log.warning(
            "redis_classification_persist_failed",
            batch_id=batch_id,
            atom_id=event.atom_id,
            error=str(exc),
        )


def _publish_async(
    redis: RedisPubSub,
    event: Any,
    batch_id: str,
    phase: int,
) -> None:
    """Fire-and-forget async pub/sub from sync context."""
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                _pubsub_only(redis, event),
            )
        finally:
            loop.close()
    except Exception as exc:
        log.warning(
            "redis_pubsub_failed",
            batch_id=batch_id,
            phase=phase,
            error=str(exc),
        )


async def _pubsub_only(
    redis: RedisPubSub,
    event: Any,
) -> None:
    """Publish to pub/sub channel only.

    Creates a fresh async client each time to avoid
    event-loop-bound connection reuse issues.
    """
    import redis.asyncio as aioredis  # noqa: PLC0415

    channel = f"progress:{event.batch_id}"
    payload = event.model_dump_json()
    client = aioredis.from_url(
        redis._url,
        decode_responses=True,
    )
    try:
        await client.publish(channel, payload)
    finally:
        await client.close()
