"""
Celery worker — runs the DYNAFIT LangGraph pipeline.

Execution model:
  First call  → run phases 1–4 (graph pauses before Phase 5 via interrupt_before)
                check for REVIEW_REQUIRED classifications
                if none   → auto-resume Phase 5 immediately
                if some   → emit review_required event, return
  Resume call → config["_resume"] = True, skip phases 1–4, run Phase 5 directly

Progress events (phase_start, step_progress, classification) are published by
the pipeline nodes to Redis directly. This task handles only terminal events:
  complete, review_required, error.

Checkpointer:
  MemorySaver (MVP) — shared across tasks in the same worker process.
  Swap for PostgresSaver when Phase 5 is fully implemented (Session G).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import redis
import structlog
from celery import Celery
from langgraph.checkpoint.memory import MemorySaver

from modules.dynafit.graph import build_dynafit_graph
from platform.schemas.fitment import FitLabel
from platform.schemas.requirement import RawUpload

log = structlog.get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("dynafit", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
)

# Shared in-process checkpointer — allows resume in the same worker.
# Replace with PostgresSaver for multi-process / crash-recovery (Session G).
_checkpointer = MemorySaver()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _emit(batch_id: str, payload: dict[str, Any]) -> None:
    """Publish a single JSON event to progress:{batch_id} via sync Redis."""
    r = redis.from_url(REDIS_URL)
    try:
        r.publish(f"progress:{batch_id}", json.dumps(payload))
    finally:
        r.close()


def _resume_phase5(batch_id: str, thread_config: dict[str, Any]) -> None:
    """Run Phase 5 (validate) by resuming from the last checkpoint."""
    graph = build_dynafit_graph(checkpointer=_checkpointer)
    try:
        final_state: dict[str, Any] = asyncio.run(graph.ainvoke(None, config=thread_config))
    except Exception as exc:
        log.error("pipeline_phase5_failed", batch_id=batch_id, error=str(exc))
        _emit(
            batch_id,
            {
                "event": "error",
                "batch_id": batch_id,
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        return

    batch = final_state.get("validated_batch")
    fit = partial_fit = gap = review = total = 0
    if batch:
        total = batch.total_atoms
        fit = batch.fit_count
        partial_fit = batch.partial_fit_count
        gap = batch.gap_count
        review = batch.review_count

    _emit(
        batch_id,
        {
            "event": "complete",
            "batch_id": batch_id,
            "total": total,
            "fit_count": fit,
            "partial_fit_count": partial_fit,
            "gap_count": gap,
            "review_count": review,
            "report_url": f"/api/v1/d365_fo/dynafit/{batch_id}/report",
        },
    )
    log.info("pipeline_complete", batch_id=batch_id, total=total)


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


@celery_app.task(
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
                     _resume       — if True, skip to Phase 5 resume only
    """
    thread_config: dict[str, Any] = {"configurable": {"thread_id": batch_id}}

    # --- Resume path (called after HITL review is complete) ------------------
    if config.get("_resume"):
        log.info("pipeline_resume", batch_id=batch_id)
        _resume_phase5(batch_id, thread_config)
        return

    # --- Normal first-run path -----------------------------------------------
    meta = config.pop("_upload_meta", {})
    file_path = Path(str(meta.get("path", "")))

    try:
        file_bytes = file_path.read_bytes()
    except OSError as exc:
        log.error("pipeline_file_missing", batch_id=batch_id, path=str(file_path))
        _emit(
            batch_id,
            {
                "event": "error",
                "batch_id": batch_id,
                "error_type": "FileNotFoundError",
                "message": f"Upload file not found: {exc}",
            },
        )
        return

    raw_upload = RawUpload(
        upload_id=upload_id,
        product_id=str(meta.get("product", "d365_fo")),
        filename=str(meta.get("filename", "upload")),
        file_bytes=file_bytes,
        wave=int(meta.get("wave", 1)),
        country=str(meta.get("country", "")),
    )

    graph = build_dynafit_graph(checkpointer=_checkpointer)

    try:
        # Phases 1–4: graph stops before Phase 5 (interrupt_before=["validate"])
        state: dict[str, Any] = asyncio.run(
            graph.ainvoke(
                {"upload": raw_upload, "batch_id": batch_id, "errors": []},
                config=thread_config,
            )
        )
    except Exception as exc:
        log.error("pipeline_phases14_failed", batch_id=batch_id, error=str(exc))
        _emit(
            batch_id,
            {
                "event": "error",
                "batch_id": batch_id,
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return

    # --- Check if HITL is required -------------------------------------------
    classifications = state.get("classifications") or []
    review_needed = [c for c in classifications if c.classification == FitLabel.REVIEW_REQUIRED]

    if review_needed:
        _emit(
            batch_id,
            {
                "event": "review_required",
                "batch_id": batch_id,
                "review_items": len(review_needed),
                "reasons": {"low_confidence": len(review_needed)},
                "review_url": f"/review/{batch_id}",
            },
        )
        log.info("pipeline_hitl_required", batch_id=batch_id, count=len(review_needed))
        return  # Resumed via POST /d365_fo/dynafit/{batch_id}/review/complete

    # --- No HITL needed: auto-resume Phase 5 ----------------------------------
    _resume_phase5(batch_id, thread_config)
