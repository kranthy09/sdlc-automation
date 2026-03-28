"""
Integration — platform/storage/redis_pub.py

Requires a running Redis server.
Set REDIS_URL=redis://localhost:6379 to run.
Skip automatically when REDIS_URL is absent.

Tests cover:
  - publish + subscribe round-trip delivers the event
  - subscribe auto-stops after receiving a CompleteEvent
  - ErrorEvent also terminates the subscriber
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def redis_url() -> str:
    url = os.getenv("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL not set — run 'make dev' to start Redis")
    return url


@pytest.fixture
async def pubsub(redis_url: str) -> Any:  # type: ignore[misc]
    from platform.storage.redis_pub import RedisPubSub

    ps = RedisPubSub(redis_url)
    yield ps
    await ps.close()


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_publish_subscribe_round_trip(pubsub: Any) -> None:
    """Publish a PhaseStartEvent; subscriber receives it with correct fields."""
    from platform.schemas.events import PhaseStartEvent

    batch_id = "test-batch-rt"
    event = PhaseStartEvent(batch_id=batch_id, phase=1, phase_name="Parsing")

    received: list[Any] = []

    async def collect() -> None:
        async for e in pubsub.subscribe(batch_id):
            received.append(e)
            break  # collect one event then exit

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.05)  # give subscriber time to register with Redis
    await pubsub.publish(event)
    await asyncio.wait_for(task, timeout=5.0)

    assert len(received) == 1
    assert isinstance(received[0], PhaseStartEvent)
    assert received[0].batch_id == batch_id
    assert received[0].phase == 1
    assert received[0].phase_name == "Parsing"


# ---------------------------------------------------------------------------
# Auto-stop on terminal events
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_subscribe_stops_on_complete_event(pubsub: Any) -> None:
    """Generator terminates automatically after yielding a CompleteEvent."""
    from platform.schemas.events import CompleteEvent

    batch_id = "test-batch-complete"
    event = CompleteEvent(
        batch_id=batch_id,
        total=10,
        fit_count=7,
        partial_fit_count=2,
        gap_count=1,
        review_count=0,
    )

    received: list[Any] = []

    async def collect() -> None:
        async for e in pubsub.subscribe(batch_id):
            received.append(e)
            # generator should stop itself — no explicit break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.05)
    await pubsub.publish(event)
    await asyncio.wait_for(task, timeout=5.0)

    assert len(received) == 1
    assert isinstance(received[0], CompleteEvent)
    assert received[0].total == 10


@pytest.mark.integration
async def test_subscribe_stops_on_error_event(pubsub: Any) -> None:
    """Generator terminates automatically after yielding an ErrorEvent."""
    from platform.schemas.events import ErrorEvent

    batch_id = "test-batch-error"
    event = ErrorEvent(
        batch_id=batch_id,
        phase=2,
        error_type="RetrievalError",
        message="Qdrant unreachable",
    )

    received: list[Any] = []

    async def collect() -> None:
        async for e in pubsub.subscribe(batch_id):
            received.append(e)

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.05)
    await pubsub.publish(event)
    await asyncio.wait_for(task, timeout=5.0)

    assert len(received) == 1
    assert isinstance(received[0], ErrorEvent)
    assert received[0].error_type == "RetrievalError"
