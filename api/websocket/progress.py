"""
WebSocket progress handler.

Subscribes to Redis progress:{batch_id} and streams typed JSON events
to the connected browser. Stops automatically on CompleteEvent, ErrorEvent,
or ReviewRequiredEvent (RedisPubSub handles terminal-event detection).

Catch-up on reconnect:
  1. Replay persisted phase states from the batch Redis hash -- these are
     durably written by RedisPubSub.publish() for every phase lifecycle
     event, so no phase_start or phase_complete is ever lost.
  2. Check for terminal state (complete / review_required) -- if the
     pipeline already finished, send a synthetic terminal event and close.

If the client disconnects mid-stream the handler cleans up the Redis
subscription and exits.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from platform.config.settings import get_settings
from platform.schemas.events import (
    ClassificationEvent,
    CompleteEvent,
    PhaseCompleteEvent,
    PhaseGateEvent,
    PhaseStartEvent,
    ReviewRequiredEvent,
    StepProgressEvent,
)
from platform.storage.redis_pub import RedisPubSub

log = structlog.get_logger(__name__)


async def _replay_phases(
    websocket: WebSocket,
    batch: dict[str, str],
    batch_id: str,
) -> None:
    """Replay persisted phase states as synthetic WS events.

    Sends PhaseStartEvent + StepProgressEvent + PhaseCompleteEvent for
    every phase whose state is recorded in the batch hash ``phases``
    field.  This brings a newly-connected (or reconnected) client
    fully up to date without relying on pub/sub message history.
    """
    raw_phases = batch.get("phases")
    if not raw_phases:
        return

    try:
        phases: dict[str, dict[str, Any]] = json.loads(raw_phases)
    except (json.JSONDecodeError, TypeError):
        return

    # Replay in phase order (1..5)
    for phase_num in sorted(phases, key=int):
        p = phases[phase_num]
        phase = int(phase_num)
        status = p.get("status", "pending")
        name = p.get("phase_name", "")

        if status == "pending":
            continue

        # Always send phase_start for active or complete phases
        start_evt = PhaseStartEvent(
            batch_id=batch_id,
            phase=phase,
            phase_name=name,
        )
        await websocket.send_text(
            start_evt.model_dump_json(),
        )

        # Send step progress if there's a current step
        step = p.get("current_step")
        pct = p.get("progress_pct", 0)
        if step and status == "active":
            # Approximate completed/total from pct
            total = 100
            completed = pct
            step_evt = StepProgressEvent(
                batch_id=batch_id,
                phase=phase,
                step=step,
                completed=completed,
                total=total,
            )
            await websocket.send_text(
                step_evt.model_dump_json(),
            )

        if status == "complete":
            complete_evt = PhaseCompleteEvent(
                batch_id=batch_id,
                phase=phase,
                phase_name=name,
                atoms_produced=p.get("atoms_produced", 0),
                atoms_validated=p.get("atoms_validated", 0),
                atoms_flagged=p.get("atoms_flagged", 0),
                latency_ms=p.get("latency_ms", 0),
            )
            await websocket.send_text(
                complete_evt.model_dump_json(),
            )

    replayed = len(phases)
    log.info(
        "ws_replayed_phases",
        batch_id=batch_id,
        phases_replayed=replayed,
    )


async def _replay_classifications(
    websocket: WebSocket,
    batch: dict[str, str],
    batch_id: str,
) -> None:
    """Replay persisted classification events on reconnect.

    Reads the ``classifications`` field from the batch Redis hash — written
    by ``RedisPubSub.persist_classification_sync()`` during Phase 4 — and
    emits a synthetic ``ClassificationEvent`` for each stored entry.

    This ensures a reconnecting client sees all classifications that were
    produced before the disconnect, without relying on pub/sub history.
    """
    raw = batch.get("classifications")
    if not raw:
        return

    try:
        rows: list[dict[str, Any]] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return

    for entry in rows:
        try:
            evt = ClassificationEvent(
                batch_id=batch_id,
                atom_id=entry["atom_id"],
                classification=entry["classification"],
                confidence=entry["confidence"],
                requirement_text=entry.get("requirement_text", ""),
                module=entry.get("module", ""),
                rationale=entry.get("rationale", ""),
                d365_capability=entry.get("d365_capability", ""),
                d365_navigation=entry.get("d365_navigation", ""),
                journey=entry.get("journey"),
            )
            await websocket.send_text(evt.model_dump_json())
        except Exception as exc:
            log.warning(
                "ws_replay_classification_failed",
                batch_id=batch_id,
                atom_id=entry.get("atom_id"),
                error=str(exc),
            )

    log.info(
        "ws_replayed_classifications",
        batch_id=batch_id,
        count=len(rows),
    )


async def _catch_up(
    websocket: WebSocket,
    batch_id: str,
    redis_url: str,
) -> bool:
    """Replay persisted state and check for terminal events.

    Returns True if a terminal event was sent (caller should close).
    """
    batch = await RedisPubSub.read_batch_state(
        redis_url, batch_id,
    )
    if not batch:
        return False

    # 1. Replay all persisted phase states
    await _replay_phases(websocket, batch, batch_id)

    # 2. Replay all persisted classification events
    await _replay_classifications(websocket, batch, batch_id)

    # 3. Check for terminal state
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
            results_url=f"/results/{batch_id}",
        )
        await websocket.send_text(
            event.model_dump_json(),
        )
        log.info(
            "ws_replayed_complete",
            batch_id=batch_id,
        )
        return True

    if status == "review_required":
        items = json.loads(
            batch.get("review_items", "[]"),
        )
        reasons: dict[str, int] = {}
        for item in items:
            rr = item.get(
                "review_reason",
                "low_confidence",
            )
            reasons[rr] = reasons.get(rr, 0) + 1
        if not reasons:
            reasons = {"low_confidence": len(items)}
        review_event = ReviewRequiredEvent(
            batch_id=batch_id,
            review_items=len(items),
            reasons=reasons,
            review_url=f"/review/{batch_id}",
        )
        await websocket.send_text(
            review_event.model_dump_json(),
        )
        log.info(
            "ws_replayed_review_required",
            batch_id=batch_id,
        )
        return True

    if status and status.startswith("gate_"):
        try:
            gate = int(status.split("_")[1])
        except (ValueError, IndexError):
            return False

        gate_names = {1: "Ingestion", 2: "RAG", 3: "Matching", 4: "Classification"}
        phase_name = gate_names.get(gate, f"Phase {gate + 1}")

        # Get atoms count from the corresponding Redis field
        atoms_count = 0
        field_map = {
            1: "phase1_atoms",
            2: "phase2_contexts",
            3: "phase3_matches",
            4: "classifications",
        }
        field = field_map.get(gate, "")
        if field in batch:
            try:
                if gate == 4:
                    rows = json.loads(batch.get("classifications", "[]"))
                else:
                    rows = json.loads(batch.get(field, "[]"))
                atoms_count = len(rows)
            except (json.JSONDecodeError, ValueError):
                atoms_count = 0

        gate_event = PhaseGateEvent(
            batch_id=batch_id,
            gate=gate,
            phase_name=phase_name,
            atoms_count=atoms_count,
        )
        await websocket.send_text(
            gate_event.model_dump_json(),
        )
        log.info(
            "ws_replayed_gate",
            batch_id=batch_id,
            gate=gate,
        )
        return True

    return False


async def progress_handler(
    websocket: WebSocket,
    batch_id: str,
) -> None:
    """Accept the WS and forward Redis events until done."""
    await websocket.accept()
    settings = get_settings()
    log.info("ws_connected", batch_id=batch_id)

    # Catch-up: replay persisted phases + terminal state
    if await _catch_up(
        websocket,
        batch_id,
        settings.redis_url,
    ):
        await websocket.close()
        return

    pubsub = RedisPubSub(settings.redis_url)
    try:
        async for event in pubsub.subscribe(batch_id):
            await websocket.send_text(
                event.model_dump_json(),
            )
        # Pubsub loop exited normally -- terminal event.
        await websocket.close(1000)
    except WebSocketDisconnect:
        log.info(
            "ws_client_disconnected",
            batch_id=batch_id,
        )
    except Exception as exc:
        log.error(
            "ws_error",
            batch_id=batch_id,
            error=str(exc),
        )
    finally:
        await pubsub.close()
        log.info("ws_closed", batch_id=batch_id)
