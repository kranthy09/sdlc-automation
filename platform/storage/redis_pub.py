"""
Async Redis Pub/Sub publisher and subscriber for pipeline progress events.

Channel naming: ``progress:{batch_id}``

Events are serialised as JSON (Pydantic ``model_dump_json``) and deserialised
via a TypeAdapter that resolves the discriminated union on the ``event`` field.

Subscribers auto-stop after yielding a CompleteEvent or ErrorEvent so the
WebSocket handler does not need to know about the event lifecycle itself.

**Durable phase state**: Every PhaseStartEvent, StepProgressEvent, and
PhaseCompleteEvent is automatically persisted to the ``batch:{batch_id}``
Redis hash under the ``phases`` field. This provides a crash-safe, reconnect-
safe source of truth for pipeline progress that survives pub/sub message
loss.  Any client (WebSocket catch-up, REST endpoint, page reload) can read
``phases`` from the hash instead of relying on ephemeral pub/sub delivery.

Usage:
    from platform.storage.redis_pub import RedisPubSub

    pub = RedisPubSub(settings.redis_url)

    # Pipeline worker — fire and forget
    await pub.publish(PhaseStartEvent(batch_id="b1", phase=1, phase_name="Parsing"))

    # WebSocket handler — stream to browser
    async for event in pub.subscribe("b1"):
        await ws.send_json(event.model_dump())
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import TypeAdapter

from platform.observability.logger import get_logger
from platform.schemas.events import (
    ClassificationEvent,
    CompleteEvent,
    ErrorEvent,
    PhaseCompleteEvent,
    PhaseStartEvent,
    ReviewRequiredEvent,
    StepProgressEvent,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Discriminated-union adapter
# ---------------------------------------------------------------------------

type _AnyEvent = (
    PhaseStartEvent
    | StepProgressEvent
    | ClassificationEvent
    | PhaseCompleteEvent
    | CompleteEvent
    | ErrorEvent
    | ReviewRequiredEvent
)

_adapter: TypeAdapter[Any] = TypeAdapter(
    PhaseStartEvent
    | StepProgressEvent
    | ClassificationEvent
    | PhaseCompleteEvent
    | CompleteEvent
    | ErrorEvent
    | ReviewRequiredEvent
)

_TERMINAL = (CompleteEvent, ErrorEvent, ReviewRequiredEvent)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class RedisError(Exception):
    """Raised when a Redis Pub/Sub operation fails."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)


# ---------------------------------------------------------------------------
# RedisPubSub
# ---------------------------------------------------------------------------


class RedisPubSub:
    """Async Redis publisher and subscriber for ``ProgressEvent`` streams.

    Args:
        url:      Redis DSN — ``redis://host:6379`` or ``redis://user:pw@host/0``.
        _client:  Pre-built async Redis client — for testing only.
    """

    def __init__(
        self,
        url: str,
        *,
        _client: Any = None,
    ) -> None:
        self._url = url
        self._client: Any = _client

    # ------------------------------------------------------------------
    # Client (lazy)
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis  # noqa: PLC0415

            log.info("redis_connect", url=self._url)
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def close(self) -> None:
        """Close the underlying connection. Call in test teardown."""
        if self._client is not None:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Durable phase state
    # ------------------------------------------------------------------

    async def _persist_phase_state(self, event: _AnyEvent) -> None:
        """Write phase lifecycle events to the batch Redis hash.

        The ``phases`` field stores a JSON object keyed by phase number:
            {"1": {"status": "complete", ...}, "2": {"status": "active", ...}}

        This runs BEFORE pub/sub so that if the publish is lost the durable
        record still exists.
        """
        batch_id = event.batch_id
        hash_key = f"batch:{batch_id}"
        client = self._get_client()

        try:
            raw = await client.hget(hash_key, "phases")
            phases: dict[str, dict[str, Any]] = json.loads(raw) if raw else {}
        except Exception:
            phases = {}

        key = str(event.phase)

        if isinstance(event, PhaseStartEvent):
            phases[key] = {
                "status": "active",
                "phase_name": event.phase_name,
                "current_step": None,
                "progress_pct": 0,
                "atoms_produced": 0,
                "atoms_validated": 0,
                "atoms_flagged": 0,
                "latency_ms": None,
            }
        elif isinstance(event, StepProgressEvent):
            phase = phases.get(key, {})
            pct = round((event.completed / event.total) * 100) if event.total > 0 else 0
            phase["current_step"] = event.step
            phase["progress_pct"] = pct
            phases[key] = phase
        elif isinstance(event, PhaseCompleteEvent):
            phases[key] = {
                "status": "complete",
                "phase_name": event.phase_name,
                "current_step": None,
                "progress_pct": 100,
                "atoms_produced": event.atoms_produced,
                "atoms_validated": event.atoms_validated,
                "atoms_flagged": event.atoms_flagged,
                "latency_ms": event.latency_ms,
            }
        else:
            return  # not a phase lifecycle event

        try:
            await client.hset(hash_key, "phases", json.dumps(phases))
        except Exception as exc:
            log.warning(
                "redis_phase_persist_failed",
                batch_id=batch_id,
                phase=event.phase,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Read persisted phase state (class method — no instance needed)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_phase_states(redis_url: str, batch_id: str) -> dict[str, Any]:
        """Read durable phase progress from the batch Redis hash.

        Returns the parsed ``phases`` dict, or empty dict if unavailable.
        """
        import redis.asyncio as aioredis  # noqa: PLC0415

        try:
            r = aioredis.from_url(redis_url, decode_responses=True)
            try:
                raw = await r.hget(f"batch:{batch_id}", "phases")
            finally:
                await r.aclose()
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Sync durable phase persistence (for Celery / sync callers)
    # ------------------------------------------------------------------

    @staticmethod
    def persist_phase_state_sync(
        redis_url: str,
        event: PhaseStartEvent | StepProgressEvent | PhaseCompleteEvent,
    ) -> None:
        """Synchronously persist phase state to the batch Redis hash.

        Uses sync ``redis`` (not ``redis.asyncio``) so callers in sync
        contexts (Celery workers, LangGraph nodes) never hit event-loop
        conflicts.  This is the primary durable write — the async
        ``_persist_phase_state`` in ``publish()`` is a secondary path
        used only by pure-async callers (e.g. the WebSocket handler).
        """
        import redis as sync_redis  # noqa: PLC0415

        batch_id = event.batch_id
        hash_key = f"batch:{batch_id}"

        try:
            r = sync_redis.from_url(redis_url)
            try:
                raw = r.hget(hash_key, "phases")
                phases: dict[str, dict[str, Any]] = (
                    json.loads(raw) if raw else {}
                )
            except Exception:
                phases = {}

            key = str(event.phase)

            if isinstance(event, PhaseStartEvent):
                phases[key] = {
                    "status": "active",
                    "phase_name": event.phase_name,
                    "current_step": None,
                    "progress_pct": 0,
                    "atoms_produced": 0,
                    "atoms_validated": 0,
                    "atoms_flagged": 0,
                    "latency_ms": None,
                }
            elif isinstance(event, StepProgressEvent):
                phase = phases.get(key, {})
                pct = (
                    round((event.completed / event.total) * 100)
                    if event.total > 0
                    else 0
                )
                phase["current_step"] = event.step
                phase["progress_pct"] = pct
                phases[key] = phase
            elif isinstance(event, PhaseCompleteEvent):
                phases[key] = {
                    "status": "complete",
                    "phase_name": event.phase_name,
                    "current_step": None,
                    "progress_pct": 100,
                    "atoms_produced": event.atoms_produced,
                    "atoms_validated": event.atoms_validated,
                    "atoms_flagged": event.atoms_flagged,
                    "latency_ms": event.latency_ms,
                }
            else:
                return

            r.hset(hash_key, "phases", json.dumps(phases))
        except Exception as exc:
            log.warning(
                "redis_phase_persist_sync_failed",
                batch_id=batch_id,
                phase=event.phase,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, event: _AnyEvent) -> None:
        """Serialise *event* as JSON and publish to ``progress:{batch_id}``.

        Phase lifecycle events (start, step_progress, complete) are also
        persisted to the batch Redis hash so progress survives pub/sub loss.

        Args:
            event: Any concrete ProgressEvent subclass.
        """
        # Persist phase state FIRST — durable even if pub/sub delivery fails
        if isinstance(event, (PhaseStartEvent, StepProgressEvent, PhaseCompleteEvent)):
            await self._persist_phase_state(event)

        channel = f"progress:{event.batch_id}"
        payload = event.model_dump_json()
        client = self._get_client()
        try:
            await client.publish(channel, payload)
            log.debug("redis_published", channel=channel, event_type=event.event)
        except RedisError:
            raise
        except Exception as exc:
            raise RedisError(f"publish to {channel!r} failed: {exc}", cause=exc) from exc

    # ------------------------------------------------------------------
    # Subscribe
    # ------------------------------------------------------------------

    async def subscribe(self, batch_id: str) -> AsyncGenerator[_AnyEvent, None]:
        """Subscribe to ``progress:{batch_id}`` and yield deserialised events.

        The generator stops automatically after yielding a ``CompleteEvent``
        or ``ErrorEvent`` and always unsubscribes on exit.

        Args:
            batch_id: The pipeline batch identifier to listen on.
        """
        channel = f"progress:{batch_id}"
        client = self._get_client()
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(channel)
            log.info("redis_subscribed", channel=channel)

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event: _AnyEvent = _adapter.validate_json(message["data"])
                except Exception as exc:
                    log.warning("redis_bad_message", channel=channel, error=str(exc))
                    continue
                yield event
                if isinstance(event, _TERMINAL):
                    break
        except RedisError:
            raise
        except Exception as exc:
            raise RedisError(f"subscribe({batch_id!r}) failed: {exc}", cause=exc) from exc
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass
            log.info("redis_unsubscribed", channel=channel)
