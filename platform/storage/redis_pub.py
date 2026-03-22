"""
Async Redis Pub/Sub publisher and subscriber for pipeline progress events.

Channel naming: ``progress:{batch_id}``

Events are serialised as JSON (Pydantic ``model_dump_json``) and deserialised
via a TypeAdapter that resolves the discriminated union on the ``event`` field.

Subscribers auto-stop after yielding a CompleteEvent or ErrorEvent so the
WebSocket handler does not need to know about the event lifecycle itself.

Every Redis call is wrapped in ``record_call("redis", ...)`` for Prometheus.

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

from collections.abc import AsyncGenerator
from typing import Any

from prometheus_client import CollectorRegistry
from pydantic import TypeAdapter

from platform.observability.logger import get_logger
from platform.observability.metrics import (
    MetricsRecorder,
    record_call as _default_record_call,
)
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
        registry: Prometheus CollectorRegistry. Inject a fresh one in tests.
        _client:  Pre-built async Redis client — for testing only.
    """

    def __init__(
        self,
        url: str,
        *,
        registry: CollectorRegistry | None = None,
        _client: Any = None,
    ) -> None:
        self._url = url
        self._record_call = (
            MetricsRecorder(registry).record_call
            if registry is not None
            else _default_record_call
        )
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
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, event: _AnyEvent) -> None:
        """Serialise *event* as JSON and publish to ``progress:{batch_id}``.

        Args:
            event: Any concrete ProgressEvent subclass.
        """
        channel = f"progress:{event.batch_id}"
        payload = event.model_dump_json()
        client = self._get_client()
        try:
            with self._record_call("redis", "publish"):
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
            with self._record_call("redis", "subscribe"):
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
