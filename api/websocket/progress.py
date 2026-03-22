"""
WebSocket progress handler.

Subscribes to Redis progress:{batch_id} and streams typed JSON events
to the connected browser. Stops automatically on CompleteEvent, ErrorEvent,
or ReviewRequiredEvent (RedisPubSub handles terminal-event detection).

Catch-up on reconnect: before subscribing to pub/sub, the handler checks the
Redis batch hash for a terminal state. If the pipeline already completed or
requires review, it replays a synthetic terminal event immediately so the UI
doesn't hang indefinitely when the WebSocket reconnects after events were
published (Redis pub/sub has no message persistence).

If the client disconnects mid-stream the handler cleans up the Redis
subscription and exits.
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis
import structlog
from fastapi import WebSocket, WebSocketDisconnect

from platform.config.settings import get_settings
from platform.schemas.events import CompleteEvent, ReviewRequiredEvent
from platform.storage.redis_pub import RedisPubSub

log = structlog.get_logger(__name__)


async def _replay_terminal_if_done(
    websocket: WebSocket, batch_id: str, redis_url: str
) -> bool:
    """Check Redis batch hash for a terminal state and send a synthetic event.

    Returns True if a terminal event was sent (caller should close and return).
    """
    try:
        r = aioredis.from_url(redis_url, decode_responses=True)
        try:
            batch: dict[str, str] = await r.hgetall(f"batch:{batch_id}")
        finally:
            await r.aclose()
    except Exception:
        return False  # Redis unavailable — fall through to live pub/sub

    status = batch.get("status")

    if status == "complete":
        summary = json.loads(batch.get("summary", "{}"))
        event = CompleteEvent(
            batch_id=batch_id,
            total=summary.get("total", 0),
            fit_count=summary.get("fit", 0),
            partial_fit_count=summary.get("partial_fit", 0),
            gap_count=summary.get("gap", 0),
            review_count=0,
            report_url=batch.get("report_path") or None,
        )
        await websocket.send_text(event.model_dump_json())
        log.info("ws_replayed_complete", batch_id=batch_id)
        return True

    if status == "review_required":
        review_items = json.loads(batch.get("review_items", "[]"))
        reasons_counts: dict[str, int] = {}
        for item in review_items:
            rr = item.get("review_reason", "low_confidence")
            reasons_counts[rr] = reasons_counts.get(rr, 0) + 1
        if not reasons_counts:
            reasons_counts = {"low_confidence": len(review_items)}
        event = ReviewRequiredEvent(
            batch_id=batch_id,
            review_items=len(review_items),
            reasons=reasons_counts,
            review_url=f"/review/{batch_id}",
        )
        await websocket.send_text(event.model_dump_json())
        log.info("ws_replayed_review_required", batch_id=batch_id)
        return True

    return False


async def progress_handler(websocket: WebSocket, batch_id: str) -> None:
    """Accept the WebSocket and forward Redis events until pipeline completes."""
    await websocket.accept()
    settings = get_settings()
    log.info("ws_connected", batch_id=batch_id)

    # Catch-up: replay terminal state for reconnecting clients who missed events
    if await _replay_terminal_if_done(websocket, batch_id, settings.redis_url):
        await websocket.close()
        return

    pubsub = RedisPubSub(settings.redis_url)
    try:
        async for event in pubsub.subscribe(batch_id):
            await websocket.send_text(event.model_dump_json())
        # Pubsub loop exited normally — pipeline reached a terminal event.
        # Close with 1000 so the client knows not to reconnect.
        await websocket.close(1000)
    except WebSocketDisconnect:
        log.info("ws_client_disconnected", batch_id=batch_id)
    except Exception as exc:
        log.error("ws_error", batch_id=batch_id, error=str(exc))
    finally:
        await pubsub.close()
        log.info("ws_closed", batch_id=batch_id)
