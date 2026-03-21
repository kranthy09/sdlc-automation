"""
WebSocket progress handler.

Subscribes to Redis progress:{batch_id} and streams typed JSON events
to the connected browser. Stops automatically on CompleteEvent or ErrorEvent
(RedisPubSub handles the terminal-event detection internally).

If the client disconnects mid-stream the handler cleans up the Redis
subscription and exits — no data is lost as events remain in Redis until
the channel expires.
"""

from __future__ import annotations

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from platform.config.settings import get_settings
from platform.storage.redis_pub import RedisPubSub

log = structlog.get_logger(__name__)


async def progress_handler(websocket: WebSocket, batch_id: str) -> None:
    """Accept the WebSocket and forward Redis events until pipeline completes."""
    await websocket.accept()
    settings = get_settings()
    pubsub = RedisPubSub(settings.redis_url)
    log.info("ws_connected", batch_id=batch_id)

    try:
        async for event in pubsub.subscribe(batch_id):
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        log.info("ws_client_disconnected", batch_id=batch_id)
    except Exception as exc:
        log.error("ws_error", batch_id=batch_id, error=str(exc))
    finally:
        await pubsub.close()
        log.info("ws_closed", batch_id=batch_id)
