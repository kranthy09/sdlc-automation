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

import redis
import structlog
from celery import Celery
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command

from modules.dynafit.graph import build_dynafit_graph
from platform.schemas.requirement import RawUpload

log = structlog.get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Strip the +asyncpg SQLAlchemy driver spec — psycopg3 uses plain postgresql://
POSTGRES_CHECKPOINT_URL = os.getenv(
    "POSTGRES_URL", "postgresql://localhost/dynafit"
).replace("postgresql+asyncpg://", "postgresql://")

celery_app = Celery("dynafit", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
)

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


def _write_batch_state(batch_id: str, **fields: str) -> None:
    """Write batch state fields to Redis hash batch:{batch_id}.

    All values must be pre-serialized strings (use json.dumps for dicts/lists).
    The hash has a 24-hour TTL — long enough for any review workflow.
    This is the cross-process bridge: the Celery worker writes here so the
    FastAPI routes process (separate OS process, no shared memory) can read
    results, review_items, status, summary, and report_path.
    """
    r = redis.from_url(REDIS_URL)
    try:
        key = f"batch:{batch_id}"
        r.hset(key, mapping=fields)
        r.expire(key, 86400)  # 24 h TTL
    finally:
        r.close()


def _finish_complete(batch_id: str, final_state: dict[str, Any]) -> None:
    """Write completed batch results to Redis.

    CompleteEvent is published by validation_node itself via Redis pub/sub.
    This write makes the data queryable via REST (separate OS process).
    """
    vb = final_state.get("validated_batch")
    if not vb:
        log.warning("pipeline_complete_no_batch", batch_id=batch_id)
        return

    # Build atom-keyed lookups from Phase 3 (MatchResult) and Phase 2
    # (AssembledContext) to populate evidence fields per result.
    match_by_atom = {
        mr.atom.atom_id: mr
        for mr in (final_state.get("match_results") or [])
    }
    context_by_atom = {
        ctx.atom.atom_id: ctx
        for ctx in (final_state.get("retrieval_contexts") or [])
    }

    result_dicts = []
    by_module: dict[str, dict[str, int]] = {}

    for r in vb.results:
        mr = match_by_atom.get(r.atom_id)
        ctx = context_by_atom.get(r.atom_id)

        evidence = {
            "top_capability_score": mr.top_composite_score if mr else 0.0,
            "retrieval_confidence": ctx.retrieval_confidence if ctx else "LOW",
            "prior_fitments": [
                {
                    "wave": pf.wave,
                    "country": pf.country,
                    "classification": pf.classification,
                }
                for pf in (ctx.prior_fitments if ctx else [])
            ],
        }

        d365_navigation = (
            mr.ranked_capabilities[0].navigation
            if mr and mr.ranked_capabilities
            else ""
        )

        result_dicts.append({
            "atom_id": r.atom_id,
            "requirement_text": r.requirement_text,
            "classification": str(r.classification),
            "confidence": r.confidence,
            "module": r.module,
            "country": r.country,
            "wave": r.wave,
            "rationale": r.rationale,
            "reviewer_override": False,
            "d365_capability": r.d365_capability_ref or "",
            "d365_navigation": d365_navigation,
            "evidence": evidence,
        })

        # Accumulate by_module counts (REVIEW_REQUIRED not counted)
        cls = str(r.classification)
        if cls in ("FIT", "PARTIAL_FIT", "GAP"):
            mod = by_module.setdefault(
                r.module, {"fit": 0, "partial_fit": 0, "gap": 0}
            )
            if cls == "FIT":
                mod["fit"] += 1
            elif cls == "PARTIAL_FIT":
                mod["partial_fit"] += 1
            else:
                mod["gap"] += 1

    _write_batch_state(
        batch_id,
        status="complete",
        results=json.dumps(result_dicts),
        summary=json.dumps(
            {
                "total": vb.total_atoms,
                "fit": vb.fit_count,
                "partial_fit": vb.partial_fit_count,
                "gap": vb.gap_count,
                "by_module": by_module,
            }
        ),
        report_path=vb.report_path or "",
        completed_at=datetime.now(UTC).isoformat(),
    )
    log.info("pipeline_complete", batch_id=batch_id, total=vb.total_atoms)


# Flag strings produced by Phase 5 _check_flags() that indicate a structural
# anomaly rather than simple low confidence. Mapped to "anomaly" in the UI.
_ANOMALY_FLAG_NAMES = frozenset({
    "phase3_anomaly",
    "high_confidence_gap",
    "low_score_fit",
    "llm_schema_retry_exhausted",
})


def _review_reason(flags: list[str]) -> str:
    """Map a Phase 5 flag list to the UI review_reason discriminator."""
    if any(f in _ANOMALY_FLAG_NAMES for f in flags):
        return "anomaly"
    return "low_confidence"


def _finish_hitl(
    batch_id: str,
    final_state: dict[str, Any],
    flagged_ids: set[str],
    flagged_reasons: dict[str, list[str]],
) -> None:
    """Write review_required state to Redis and emit the review_required event.

    flagged_ids / flagged_reasons come from Phase 5's interrupt() payload.
    Full ClassificationResult objects are read from final_state so the review
    queue has rationale, confidence, and requirement_text for the UI.
    Phase 2/3 state is also read to populate evidence (capabilities, prior
    fitments, anomaly flags) for each review item.
    """
    classifications = final_state.get("classifications") or []
    review_needed = [c for c in classifications if c.atom_id in flagged_ids]

    match_by_atom = {
        mr.atom.atom_id: mr
        for mr in (final_state.get("match_results") or [])
    }
    context_by_atom = {
        ctx.atom.atom_id: ctx
        for ctx in (final_state.get("retrieval_contexts") or [])
    }

    review_item_dicts = []
    reasons_counts: dict[str, int] = {}
    for c in review_needed:
        mr = match_by_atom.get(c.atom_id)
        ctx = context_by_atom.get(c.atom_id)

        anomaly_flags = mr.anomaly_flags if mr else []
        item_flags = flagged_reasons.get(c.atom_id, [])
        review_reason = _review_reason(item_flags) if item_flags else (
            "anomaly" if anomaly_flags else "low_confidence"
        )
        reasons_counts[review_reason] = reasons_counts.get(review_reason, 0) + 1

        review_item_dicts.append({
            "atom_id": c.atom_id,
            "requirement_text": c.requirement_text,
            "ai_classification": str(c.classification),
            "ai_confidence": c.confidence,
            "ai_rationale": c.rationale,
            "review_reason": review_reason,
            "evidence": {
                "capabilities": [
                    {
                        "name": cap.feature,
                        "score": cap.composite_score,
                        "navigation": cap.navigation,
                    }
                    for cap in (mr.ranked_capabilities[:3] if mr else [])
                ],
                "prior_fitments": [
                    {
                        "wave": pf.wave,
                        "country": pf.country,
                        "classification": pf.classification,
                    }
                    for pf in (ctx.prior_fitments if ctx else [])
                ],
                "anomaly_flags": anomaly_flags,
            },
        })

    # Build auto-approved items (classifications NOT flagged for review)
    auto_approved_dicts = []
    fit_count = partial_fit_count = gap_count = 0

    for c in classifications:
        cls = str(c.classification)
        if cls == "FIT":
            fit_count += 1
        elif cls == "PARTIAL_FIT":
            partial_fit_count += 1
        elif cls == "GAP":
            gap_count += 1

        if c.atom_id in flagged_ids:
            continue

        mr = match_by_atom.get(c.atom_id)
        d365_navigation = (
            mr.ranked_capabilities[0].navigation
            if mr and mr.ranked_capabilities
            else ""
        )
        auto_approved_dicts.append({
            "atom_id": c.atom_id,
            "requirement_text": c.requirement_text,
            "classification": cls,
            "confidence": c.confidence,
            "module": c.module,
            "rationale": c.rationale,
            "d365_capability": c.d365_capability_ref or "",
            "d365_navigation": d365_navigation,
        })

    _write_batch_state(
        batch_id,
        status="review_required",
        review_items=json.dumps(review_item_dicts),
        auto_approved=json.dumps(auto_approved_dicts),
        summary=json.dumps({
            "total": len(classifications),
            "fit": fit_count,
            "partial_fit": partial_fit_count,
            "gap": gap_count,
        }),
    )
    _emit(
        batch_id,
        {
            "event": "review_required",
            "batch_id": batch_id,
            "review_items": len(review_needed),
            "reasons": reasons_counts,
            "review_url": f"/review/{batch_id}",
        },
    )
    log.info("pipeline_hitl_required", batch_id=batch_id, count=len(review_needed))


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
        return await graph.ainvoke(Command(resume=overrides), config=thread_config)


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
                     _resume       — if True, deliver HITL overrides to Phase 5
                     _overrides    — human review decisions (keyed by atom_id)
    """
    thread_config: dict[str, Any] = {"configurable": {"thread_id": batch_id}}

    # --- Resume path (called after HITL review is complete) ------------------
    if config.get("_resume"):
        overrides: dict[str, Any] = config.get("_overrides", {})
        log.info(
            "pipeline_resume",
            batch_id=batch_id,
            override_count=len(overrides),
        )
        try:
            final_state = asyncio.run(
                _resume_phase5_hitl(batch_id, thread_config, overrides)
            )
        except Exception as exc:
            log.error("pipeline_phase5_resume_failed", batch_id=batch_id, error=str(exc))
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
        _finish_complete(batch_id, final_state)
        return

    # --- Normal first-run path -----------------------------------------------
    # Extract per-run threshold overrides before consuming the rest of config.
    # These keys are recognized ProductConfig fields the UI may override.
    _OVERRIDE_KEYS = {"fit_confidence_threshold", "review_confidence_threshold", "auto_approve_with_history"}
    run_overrides: dict[str, Any] = {k: v for k, v in config.items() if k in _OVERRIDE_KEYS}

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

    async def _run_phases14() -> dict[str, Any]:
        async with AsyncPostgresSaver.from_conn_string(
            POSTGRES_CHECKPOINT_URL, serde=JsonPlusSerializer()
        ) as checkpointer:
            await checkpointer.setup()
            graph = build_dynafit_graph(checkpointer=checkpointer)
            initial_state: dict[str, Any] = {
                "upload": raw_upload,
                "batch_id": batch_id,
                "errors": [],
            }
            if run_overrides:
                initial_state["config_overrides"] = run_overrides
            return await graph.ainvoke(initial_state, config=thread_config)

    try:
        # Phases 1–4: graph stops before Phase 5 (interrupt_before=["validate"])
        asyncio.run(_run_phases14())
    except Exception as exc:
        log.error(
            "pipeline_phases14_failed",
            batch_id=batch_id,
            error=str(exc),
        )
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

    # --- Enter Phase 5 (resume from interrupt_before checkpoint) -------------
    # Phase 5's sanity gate decides what needs review and calls interrupt()
    # if needed — the worker does NOT pre-screen classifications here.
    try:
        outcome, final_state, flagged_ids, flagged_reasons = asyncio.run(
            _run_phase5(batch_id, thread_config)
        )
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

    if outcome == "complete":
        _finish_complete(batch_id, final_state)
    else:
        _finish_hitl(batch_id, final_state, flagged_ids, flagged_reasons)
