"""
Celery worker — runs the DYNAFIT LangGraph pipeline.

Execution model:
  First call  → run phases 1–4 (graph pauses before Phase 5 via
                interrupt_before), then immediately enter Phase 5:
                  Phase 5 sanity gate runs:
                    nothing flagged → complete; write results to Redis
                    items flagged   → Phase 5 calls interrupt(); graph
                                      pauses; emit review_required, return
  Resume call → config["_resume"] = True
                → Command(resume=overrides) delivers human decisions to
                  interrupt() inside Phase 5, which then completes

Two LangGraph pause points — handled differently:
  interrupt_before=["validate"]  → resume with graph.ainvoke(None, ...)
  interrupt() inside validate    → resume with graph.ainvoke(Command(resume=overrides), ...)

Progress events (phase_start, step_progress, classification) are published by
the pipeline nodes to Redis directly. This task handles only terminal events:
  complete, review_required, error.

Checkpointer:
  AsyncPostgresSaver — stores graph snapshots in PostgreSQL so any
  worker process can resume a paused batch (cross-process safe).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from celery import Celery
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command

from modules.dynafit.graph import build_dynafit_graph
from modules.dynafit.presentation import (
    build_complete_data,
    build_hitl_data,
)
from platform.schemas.events import ErrorEvent, ReviewRequiredEvent
from platform.schemas.requirement import RawUpload
from platform.storage.redis_pub import RedisPubSub

log = structlog.get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Strip the +asyncpg SQLAlchemy driver spec — psycopg3 uses plain postgresql://
_raw_pg = os.getenv(
    "POSTGRES_URL", "postgresql://localhost/dynafit",
)
POSTGRES_CHECKPOINT_URL = _raw_pg.replace(
    "postgresql+asyncpg://", "postgresql://",
)

celery_app = Celery("dynafit", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
)

# ---------------------------------------------------------------------------
# Internal helpers — all go through platform/storage/redis_pub
# ---------------------------------------------------------------------------


def _emit_error(
    batch_id: str,
    exc: Exception,
) -> None:
    """Publish a typed ErrorEvent via platform abstraction."""
    event = ErrorEvent(
        batch_id=batch_id,
        error_type=type(exc).__name__,
        message=str(exc),
    )
    RedisPubSub.publish_sync(REDIS_URL, event)


def _write_batch_state(batch_id: str, **fields: str) -> None:
    """Write batch state fields via platform abstraction."""
    RedisPubSub.write_batch_state_sync(
        REDIS_URL, batch_id, **fields,
    )


def _finish_complete(
    batch_id: str, final_state: dict[str, Any]
) -> None:
    """Write completed batch results to Redis."""
    data = build_complete_data(final_state)
    if not data:
        log.warning(
            "pipeline_complete_no_batch", batch_id=batch_id
        )
        return

    _write_batch_state(
        batch_id,
        status="complete",
        results=json.dumps(data["results"]),
        summary=json.dumps(data["summary"]),
        journey=json.dumps(data["journey"]),
        report_path=data["report_path"],
        completed_at=datetime.now(UTC).isoformat(),
    )
    log.info(
        "pipeline_complete",
        batch_id=batch_id,
        total=data["total_atoms"],
    )


def _finish_hitl(
    batch_id: str,
    final_state: dict[str, Any],
    flagged_ids: set[str],
    flagged_reasons: dict[str, list[str]],
) -> None:
    """Write review_required state to Redis."""
    data = build_hitl_data(
        final_state, flagged_ids, flagged_reasons
    )

    _write_batch_state(
        batch_id,
        status="review_required",
        review_items=json.dumps(data["review_items"]),
        auto_approved=json.dumps(data["auto_approved"]),
        summary=json.dumps(data["summary"]),
        journey=json.dumps(data["journey"]),
    )
    event = ReviewRequiredEvent(
        batch_id=batch_id,
        review_items=data["review_count"],
        reasons=data["reasons_counts"],
        review_url=f"/review/{batch_id}",
    )
    RedisPubSub.publish_sync(REDIS_URL, event)
    log.info(
        "pipeline_hitl_required",
        batch_id=batch_id,
        count=data["review_count"],
    )


async def _run_phase5(
    batch_id: str, thread_config: dict[str, Any]
) -> tuple[str, dict[str, Any], set[str], dict[str, list[str]]]:
    """Enter Phase 5 by resuming from the interrupt_before checkpoint.

    Passes None to graph.ainvoke() — LangGraph resumes from the saved
    checkpoint and runs the "validate" node for the first time.

    Returns a 4-tuple:
        ("complete", final_state, set(), {})        — Phase 5 finished; validated_batch present
        ("hitl",     final_state, atom_ids, reasons) — Phase 5 called interrupt(); graph paused
    """
    async with AsyncPostgresSaver.from_conn_string(
        POSTGRES_CHECKPOINT_URL, serde=JsonPlusSerializer()
    ) as checkpointer:
        await checkpointer.setup()
        graph = build_dynafit_graph(checkpointer=checkpointer)
        final_state: dict[str, Any] = await graph.ainvoke(None, config=thread_config)

        if final_state.get("validated_batch"):
            return ("complete", final_state, set(), {})

        # Phase 5 called interrupt() — graph is paused inside the validate node.
        # Retrieve the interrupt payload to learn which atoms were flagged and why.
        flagged_ids: set[str] = set()
        flagged_reasons: dict[str, list[str]] = {}
        try:
            snapshot = await graph.aget_state(thread_config)
            for task in snapshot.tasks:
                for intr in task.interrupts:
                    flagged_ids.update(intr.value.get("flagged_atom_ids", []))
                    flagged_reasons.update(intr.value.get("flagged_reasons", {}))
        except Exception as exc:
            log.warning(
                "phase5_interrupt_payload_read_failed",
                batch_id=batch_id,
                error=str(exc),
            )

        return ("hitl", final_state, flagged_ids, flagged_reasons)


async def _resume_phase5_hitl(
    batch_id: str, thread_config: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    """Resume Phase 5 after HITL review using Command(resume=overrides).

    LangGraph delivers overrides as the return value of interrupt() inside
    the validation node. The node then continues and completes normally,
    producing a ValidatedFitmentBatch in the returned state.
    """
    async with AsyncPostgresSaver.from_conn_string(
        POSTGRES_CHECKPOINT_URL, serde=JsonPlusSerializer()
    ) as checkpointer:
        graph = build_dynafit_graph(checkpointer=checkpointer)
        state: dict[str, Any] = await graph.ainvoke(Command(resume=overrides), config=thread_config)
        return state


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="api.workers.tasks.run_dynafit_pipeline",
    max_retries=2,
    default_retry_delay=30,
)
def run_dynafit_pipeline(
    self: Any,
    batch_id: str,
    upload_id: str,
    config: dict[str, Any],
) -> None:
    """Execute the full DYNAFIT pipeline for a single batch.

    Args:
        batch_id:  Unique batch identifier (also used as LangGraph thread_id).
        upload_id: Source upload identifier.
        config:    Config overrides from the API. Special keys:
                     _upload_meta  — upload metadata dict (filename, path, …)
                     _resume       — if True, deliver HITL overrides to Phase 5
                     _overrides    — human review decisions (keyed by atom_id)
    """
    thread_config: dict[str, Any] = {"configurable": {"thread_id": batch_id}}

    # --- Resume path (after HITL review) -----------
    if config.get("_resume"):
        overrides: dict[str, Any] = config.get("_overrides", {})
        log.info(
            "pipeline_resume",
            batch_id=batch_id,
            override_count=len(overrides),
        )
        try:
            final_state = asyncio.run(
                _resume_phase5_hitl(
                    batch_id, thread_config, overrides,
                ),
            )
        except Exception as exc:
            log.error(
                "pipeline_phase5_resume_failed",
                batch_id=batch_id,
                error=str(exc),
            )
            _emit_error(batch_id, exc)
            return
        _finish_complete(batch_id, final_state)
        return

    # --- Normal first-run path ----------------------
    _OVERRIDE_KEYS = {
        "fit_confidence_threshold",
        "review_confidence_threshold",
        "auto_approve_with_history",
    }
    run_overrides: dict[str, Any] = {
        k: v for k, v in config.items()
        if k in _OVERRIDE_KEYS
    }

    meta = config.pop("_upload_meta", {})
    file_path = Path(str(meta.get("path", "")))

    try:
        file_bytes = file_path.read_bytes()
    except OSError as exc:
        log.error(
            "pipeline_file_missing",
            batch_id=batch_id,
            path=str(file_path),
        )
        _emit_error(batch_id, exc)
        return

    raw_upload = RawUpload(
        upload_id=upload_id,
        product_id=str(meta.get("product", "d365_fo")),
        filename=str(meta.get("filename", "upload")),
        file_bytes=file_bytes,
        wave=int(meta.get("wave", 1)),
        country=str(meta.get("country", "")),
    )

    # Single event loop for phases 1-4 + phase 5
    async def _run_all() -> tuple[
        str, dict[str, Any], set[str], dict[str, list[str]],
    ]:
        async with AsyncPostgresSaver.from_conn_string(
            POSTGRES_CHECKPOINT_URL,
            serde=JsonPlusSerializer(),
        ) as checkpointer:
            await checkpointer.setup()
            graph = build_dynafit_graph(
                checkpointer=checkpointer,
            )
            initial: dict[str, Any] = {
                "upload": raw_upload,
                "batch_id": batch_id,
                "errors": [],
            }
            if run_overrides:
                initial["config_overrides"] = run_overrides

            # Phases 1-4 (interrupt_before=["validate"])
            await graph.ainvoke(
                initial, config=thread_config,
            )

            # Phase 5 — resume from interrupt_before
            return await _run_phase5(
                batch_id, thread_config,
            )

    try:
        outcome, final_state, flagged_ids, flagged_reasons = (
            asyncio.run(_run_all())
        )
    except Exception as exc:
        log.error(
            "pipeline_failed",
            batch_id=batch_id,
            error=str(exc),
        )
        _emit_error(batch_id, exc)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return

    if outcome == "complete":
        _finish_complete(batch_id, final_state)
    else:
        _finish_hitl(
            batch_id, final_state,
            flagged_ids, flagged_reasons,
        )
