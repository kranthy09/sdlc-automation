"""
Celery worker — runs the REQFIT LangGraph pipeline.

Execution model:
  First call  → run phases 1–4 (graph pauses before Phase 5 via
                interrupt_before), then immediately enter Phase 5:
                  Phase 5 sanity gate runs:
                    nothing flagged → complete; write to PostgreSQL
                                      (durable) + Redis (transient)
                    items flagged   → Phase 5 calls interrupt(); graph
                                      pauses; emit review_required, return
  Resume call → config["_resume"] = True
                → Command(resume=overrides) delivers human decisions to
                  interrupt() inside Phase 5, which then completes

Two LangGraph pause points — handled differently:
  interrupt_before=["validate"]  → resume with graph.ainvoke(None, ...)
  interrupt() inside validate    → resume with graph.ainvoke(Command(resume=overrides), ...)

Progress events (phase_start, step_progress, classification) are published by
the pipeline nodes to Redis directly. Terminal events (complete, review_required,
error) are written to PostgreSQL (durable) with transient state to Redis.

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
from platform.schemas.events import ErrorEvent, PhaseGateEvent, ReviewRequiredEvent
from platform.schemas.requirement import RawUpload
from platform.storage.postgres import PostgresStore
from platform.storage.redis_pub import RedisPubSub

log = structlog.get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# PostgreSQL URLs
_raw_pg = os.getenv(
    "POSTGRES_URL", "postgresql+asyncpg://localhost/dynafit",
)
POSTGRES_ASYNC_URL = _raw_pg
# Strip the +asyncpg SQLAlchemy driver spec — psycopg3 uses plain postgresql://
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


# ---------------------------------------------------------------------------
# Gate data extraction helpers
# ---------------------------------------------------------------------------


def _extract_gate1_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract ingestion phase summary from state (gate 1).

    state["validated_atoms"] is list[ValidatedAtom] — Pydantic models, not dicts.
    completeness_score is 0–100 (per ValidatedAtom schema); sent as-is.
    specificity_score is 0–1.
    """
    rows: list[dict[str, Any]] = []
    for atom in state.get("validated_atoms", []):
        rows.append({
            "atom_id": atom.atom_id,
            "requirement_text": atom.requirement_text,
            "intent": atom.intent,
            "module": atom.module,
            "priority": atom.priority,
            "completeness_score": atom.completeness_score,  # 0–100
            "specificity_score": atom.specificity_score,    # 0–1
        })
    return rows


def _extract_gate2_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract retrieval phase summary from state (gate 2).

    state["retrieval_contexts"] is list[AssembledContext] — Pydantic models.
    atom_id / requirement_text live on ctx.atom (a nested ValidatedAtom).
    Top capability is ctx.capabilities[0] (a RankedCapability); score is 0–1.
    """
    rows: list[dict[str, Any]] = []
    for ctx in state.get("retrieval_contexts", []):
        top_cap = ctx.capabilities[0] if ctx.capabilities else None
        rows.append({
            "atom_id": ctx.atom.atom_id,
            "requirement_text": ctx.atom.requirement_text,
            "top_capability": top_cap.feature if top_cap else "",
            "top_capability_score": top_cap.composite_score if top_cap else 0.0,  # 0–1
            "retrieval_confidence": ctx.retrieval_confidence,
        })
    return rows


def _extract_gate3_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract matching phase summary from state (gate 3).

    state["match_results"] is list[MatchResult] — Pydantic models.
    atom_id / requirement_text live on match.atom (a nested ValidatedAtom).
    Composite score is match.top_composite_score (0–1).
    """
    rows: list[dict[str, Any]] = []
    for match in state.get("match_results", []):
        rows.append({
            "atom_id": match.atom.atom_id,
            "requirement_text": match.atom.requirement_text,
            "composite_score": match.top_composite_score,  # 0–1
            "route": match.route,
            "anomaly_flags": match.anomaly_flags,
        })
    return rows


async def _extract_interrupt_payload(
    graph: Any, thread_config: dict[str, Any]
) -> tuple[set[str], dict[str, list[str]]]:
    """Extract flagged atom IDs and reasons from graph interrupt state.

    Returns (flagged_ids, flagged_reasons) for HITL review.
    """
    flagged_ids: set[str] = set()
    flagged_reasons: dict[str, list[str]] = {}
    try:
        snapshot = await graph.aget_state(thread_config)
        for task in snapshot.tasks:
            for intr in task.interrupts:
                flagged_ids.update(intr.value.get("flagged_atom_ids", []))
                flagged_reasons.update(
                    intr.value.get("flagged_reasons", {}))
    except Exception as exc:
        log.warning(
            "interrupt_payload_extract_failed",
            error=str(exc),
        )
    return flagged_ids, flagged_reasons


async def _update_batch_complete(
    batch_id: str,
    completed_at: datetime,
    report_path: str,
    summary: dict[str, Any],
    pg: PostgresStore,
) -> None:
    """Write batch completion to PostgreSQL (source of truth)."""
    try:
        await pg.update_batch_on_complete(
            batch_id=batch_id,
            completed_at=completed_at,
            report_path=report_path,
            summary=summary,
        )
        log.debug(
            "batch_completion_saved_to_postgres",
            batch_id=batch_id,
        )
    except Exception as exc:
        log.error(
            "batch_completion_postgres_write_failed",
            batch_id=batch_id,
            error=str(exc),
        )
        raise


async def _update_batch_review_required(
    batch_id: str,
    pg: PostgresStore,
) -> None:
    """Write review_required status to PostgreSQL."""
    try:
        await pg.update_batch_status(batch_id, status="review_required")
        log.debug(
            "batch_review_required_saved_to_postgres",
            batch_id=batch_id,
        )
    except Exception as exc:
        log.error(
            "batch_review_required_postgres_write_failed",
            batch_id=batch_id,
            error=str(exc),
        )
        raise


async def _update_batch_error(
    batch_id: str,
) -> None:
    """Write error status to PostgreSQL."""
    pg = PostgresStore(POSTGRES_ASYNC_URL)
    try:
        await pg.ensure_schema()
        await pg.update_batch_status(batch_id, status="error")
        log.debug(
            "batch_error_saved_to_postgres",
            batch_id=batch_id,
        )
    except Exception as exc:
        log.error(
            "batch_error_postgres_write_failed",
            batch_id=batch_id,
            error=str(exc),
        )
        raise
    finally:
        await pg.dispose()


async def _update_batch_status_sync(
    batch_id: str,
    status: str,
    pg: PostgresStore,
) -> None:
    """Write batch status to PostgreSQL (async helper)."""
    try:
        await pg.update_batch_status(batch_id, status=status)
        log.debug(
            "batch_status_updated_postgres",
            batch_id=batch_id,
            status=status,
        )
    except Exception as exc:
        log.warning(
            "batch_status_postgres_write_failed",
            batch_id=batch_id,
            status=status,
            error=str(exc),
        )
        # Don't raise - status update is not critical for pipeline execution


async def _finish_complete(
    batch_id: str,
    final_state: dict[str, Any],
    pg: PostgresStore,
) -> None:
    """Write completed batch results to PostgreSQL + Redis.

    PostgreSQL: status, completed_at, report_path, summary, batch_results (durable)
    Redis: journey (transient, for WebSocket progress queries)
    """
    data = build_complete_data(final_state)
    if not data:
        log.warning(
            "pipeline_complete_no_batch", batch_id=batch_id
        )
        return

    completed_at = datetime.now(UTC)

    # Write durable state to PostgreSQL
    await _update_batch_complete(
        batch_id=batch_id,
        completed_at=completed_at,
        report_path=data["report_path"],
        summary=data["summary"],
        pg=pg,
    )

    # Write per-atom results to PostgreSQL (durable, source of truth for /results API)
    try:
        await pg.save_batch_results(batch_id, data["results"])
        log.debug(
            "batch_results_saved_to_postgres",
            batch_id=batch_id,
            count=len(data["results"]),
        )
    except Exception as exc:
        log.error(
            "batch_results_postgres_write_failed",
            batch_id=batch_id,
            error=str(exc),
        )
        # Don't raise — results saving is non-critical if batch summary is saved

    # Write transient state to Redis (for live progress queries)
    _write_batch_state(
        batch_id,
        journey=json.dumps(data["journey"]),
    )

    log.info(
        "pipeline_complete",
        batch_id=batch_id,
        total=data["total_atoms"],
    )


async def _finish_hitl(
    batch_id: str,
    final_state: dict[str, Any],
    flagged_ids: set[str],
    flagged_reasons: dict[str, list[str]],
    pg: PostgresStore,
) -> None:
    """Write review_required state to PostgreSQL + Redis.

    PostgreSQL: status="review_required", auto_approved results (durable)
    Redis: review_items, auto_approved, journey, summary (in-flight;
           summary is temporary and replaced when Phase 5 resumes)
    """
    data = build_hitl_data(
        final_state, flagged_ids, flagged_reasons
    )

    # Write durable status to PostgreSQL
    await _update_batch_review_required(batch_id, pg)

    # Save flagged review items to PostgreSQL (durable review queue)
    try:
        await pg.save_review_items(batch_id, data["review_items"])
    except Exception as exc:
        log.error(
            "batch_review_items_postgres_write_failed",
            batch_id=batch_id,
            error=str(exc),
        )
        # Don't raise — review items in Redis take priority

    # Save all results (auto-approved + flagged for review) to PostgreSQL
    # so results are visible during HITL period. Flagged items will be
    # updated when Phase 5 resumes with reviewer decisions.
    # Note: review items use "ai_classification" (for review queue),
    # but batch_results expects "classification". Normalize before saving.
    try:
        flagged_for_batch = [
            {**item, "classification": item.pop("ai_classification")}
            for item in data["review_items"]
        ]
        all_results = data["auto_approved"] + flagged_for_batch
        if all_results:
            await pg.save_batch_results(batch_id, all_results)
            log.debug(
                "batch_all_results_saved_to_postgres",
                batch_id=batch_id,
                auto_approved=len(data["auto_approved"]),
                flagged=len(flagged_for_batch),
                total=len(all_results),
            )
    except Exception as exc:
        log.error(
            "batch_all_results_postgres_write_failed",
            batch_id=batch_id,
            error=str(exc),
        )
        # Don't raise — results in Redis take priority

    # Write transient state to Redis
    _write_batch_state(
        batch_id,
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
    batch_id: str, thread_config: dict[str, Any], checkpointer: Any = None
) -> tuple[str, dict[str, Any], set[str], dict[str, list[str]]]:
    """Enter Phase 5 by resuming from the interrupt_before checkpoint.

    Passes None to graph.ainvoke() — LangGraph resumes from the saved
    checkpoint and runs the "validate" node for the first time.

    Args:
        checkpointer: An already-open AsyncPostgresSaver instance. When
            provided (e.g. called from _run_all), no new DB connection is
            opened. When None, a new connection is created (standalone call).

    Returns a 4-tuple:
        ("complete", final_state, set(), {})        — Phase 5 finished; validated_batch present
        ("hitl",     final_state, atom_ids, reasons) — Phase 5 called interrupt(); graph paused
    """
    async def _execute(
        cp: Any,
    ) -> tuple[str, dict[str, Any], set[str], dict[str, list[str]]]:
        graph = build_dynafit_graph(checkpointer=cp)
        final_state: dict[str, Any] = await graph.ainvoke(None, config=thread_config)

        if final_state.get("validated_batch"):
            return ("complete", final_state, set(), {})

        # Phase 5 called interrupt() — graph is paused inside the validate node.
        # Retrieve the interrupt payload to learn which atoms were flagged and why.
        flagged_ids, flagged_reasons = await _extract_interrupt_payload(graph, thread_config)

        return ("hitl", final_state, flagged_ids, flagged_reasons)

    if checkpointer is not None:
        # Reuse the caller's connection — avoid a redundant open/setup.
        return await _execute(checkpointer)

    async with AsyncPostgresSaver.from_conn_string(
        POSTGRES_CHECKPOINT_URL, serde=JsonPlusSerializer()
    ) as cp:
        await cp.setup()
        return await _execute(cp)


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


async def _proceed_phase(
    batch_id: str,
    proceed_from_gate: int,
    thread_config: dict[str, Any],
) -> None:
    """Resume from a phase gate and run the next phase.

    For gates 1–3: resume the graph to run the next phase, pause at the next gate,
    extract summary data, publish gate event, and exit.

    For gate 4: resume the graph to run Phase 5 (validate), then handle completion
    or HITL flow.

    Args:
        batch_id:           Batch identifier
        proceed_from_gate:  Which gate to proceed from (1, 2, 3, or 4)
        thread_config:      LangGraph thread configuration
    """
    pg = PostgresStore(POSTGRES_ASYNC_URL)
    try:
        await pg.ensure_schema()
        await _update_batch_status_sync(batch_id, "processing", pg)
        _write_batch_state(batch_id, status="processing")

        async with AsyncPostgresSaver.from_conn_string(
            POSTGRES_CHECKPOINT_URL, serde=JsonPlusSerializer()
        ) as checkpointer:
            await checkpointer.setup()
            graph = build_dynafit_graph(checkpointer=checkpointer)

            # Resume from checkpoint — runs next phase, pauses at next interrupt
            state: dict[str, Any] = await graph.ainvoke(None, config=thread_config)

            if proceed_from_gate == 1:
                # Phase 2 (retrieve) just ran, paused before phase 3 (match)
                rows = _extract_gate2_rows(state)
                RedisPubSub.persist_gate_data_sync(
                    REDIS_URL, batch_id, "phase2_contexts", rows
                )
                await _update_batch_status_sync(batch_id, "gate_2", pg)
                _write_batch_state(batch_id, status="gate_2")
                gate_event = PhaseGateEvent(
                    batch_id=batch_id,
                    gate=2,
                    phase_name="RAG",
                    atoms_count=len(rows),
                )
                RedisPubSub.publish_sync(REDIS_URL, gate_event)
                log.info("gate_2_published", batch_id=batch_id, atoms_count=len(rows))

            elif proceed_from_gate == 2:
                # Phase 3 (match) just ran, paused before phase 4 (classify)
                rows = _extract_gate3_rows(state)
                RedisPubSub.persist_gate_data_sync(
                    REDIS_URL, batch_id, "phase3_matches", rows
                )
                await _update_batch_status_sync(batch_id, "gate_3", pg)
                _write_batch_state(batch_id, status="gate_3")
                gate_event = PhaseGateEvent(
                    batch_id=batch_id,
                    gate=3,
                    phase_name="Matching",
                    atoms_count=len(rows),
                )
                RedisPubSub.publish_sync(REDIS_URL, gate_event)
                log.info("gate_3_published", batch_id=batch_id, atoms_count=len(rows))

            elif proceed_from_gate == 3:
                # Phase 4 (classify) just ran, paused before phase 5 (validate)
                # Classifications already streamed live to Redis by phase 4 node
                classifications = state.get("classifications", [])
                class_count = len(classifications)
                await _update_batch_status_sync(batch_id, "gate_4", pg)
                _write_batch_state(batch_id, status="gate_4")
                gate_event = PhaseGateEvent(
                    batch_id=batch_id,
                    gate=4,
                    phase_name="Classification",
                    atoms_count=class_count,
                )
                RedisPubSub.publish_sync(REDIS_URL, gate_event)
                log.info("gate_4_published", batch_id=batch_id, atoms_count=class_count)

            elif proceed_from_gate == 4:
                # Phase 5 (validate) just ran
                # Check if it completed or needs HITL
                if state.get("validated_batch"):
                    # Phase 5 completed without issues
                    await _finish_complete(batch_id, state, pg)
                else:
                    # Phase 5 called interrupt() — needs HITL review
                    flagged_ids, flagged_reasons = await _extract_interrupt_payload(graph, thread_config)
                    await _finish_hitl(
                        batch_id, state, flagged_ids, flagged_reasons, pg
                    )

    except Exception as exc:
        log.error(
            "gate_proceed_failed",
            batch_id=batch_id,
            gate=proceed_from_gate,
            error=str(exc),
        )
        _emit_error(batch_id, exc)
        raise
    finally:
        await pg.dispose()


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
    """Execute the full REQFIT pipeline for a single batch.

    Args:
        batch_id:  Unique batch identifier (also used as LangGraph thread_id).
        upload_id: Source upload identifier.
        config:    Config overrides from the API. Special keys:
                     _upload_meta  — upload metadata dict (filename, path, …)
                     _resume       — if True, deliver HITL overrides to Phase 5
                     _overrides    — human review decisions (keyed by atom_id)
    """
    thread_config: dict[str, Any] = {"configurable": {"thread_id": batch_id}}

    # --- Gate proceed path (after analyst approves a phase gate) ----------
    if config.get("_proceed_from_gate"):
        gate_num = config["_proceed_from_gate"]
        log.info(
            "pipeline_proceed_gate",
            batch_id=batch_id,
            gate=gate_num,
        )
        try:
            asyncio.run(_proceed_phase(batch_id, gate_num, thread_config))
        except Exception as exc:
            log.error(
                "pipeline_proceed_gate_failed",
                batch_id=batch_id,
                gate=gate_num,
                error=str(exc),
            )
            _emit_error(batch_id, exc)
        return

    # --- Resume path (after HITL review) -----------
    if config.get("_resume"):
        overrides: dict[str, Any] = config.get("_overrides", {})
        log.info(
            "pipeline_resume",
            batch_id=batch_id,
            override_count=len(overrides),
        )
        async def _resume_and_finish() -> None:
            pg = PostgresStore(POSTGRES_ASYNC_URL)
            try:
                await pg.ensure_schema()
                final_state = await _resume_phase5_hitl(
                    batch_id, thread_config, overrides,
                )
                await _finish_complete(batch_id, final_state, pg)
            finally:
                await pg.dispose()

        try:
            asyncio.run(_resume_and_finish())
        except Exception as exc:
            log.error(
                "pipeline_phase5_resume_failed",
                batch_id=batch_id,
                error=str(exc),
            )
            _emit_error(batch_id, exc)
            return

    # --- Normal first-run path ----------------------
    # Parse typed configuration from API
    from api.models import PipelineConfig  # noqa: PLC0415

    try:
        pipeline_config = PipelineConfig(**config)
    except Exception as exc:
        log.error(
            "pipeline_config_parse_failed",
            batch_id=batch_id,
            error=str(exc),
        )
        _emit_error(batch_id, exc)
        return

    # Extract pipeline configuration overrides
    _OVERRIDE_KEYS = {
        "fit_confidence_threshold",
        "review_confidence_threshold",
        "auto_approve_with_history",
    }
    run_overrides: dict[str, Any] = {
        k: v for k, v in pipeline_config.config_overrides.items()
        if k in _OVERRIDE_KEYS
    }

    upload_meta = pipeline_config.upload_meta
    file_path = Path(upload_meta.path)

    try:
        file_bytes = file_path.read_bytes()
    except OSError as exc:
        log.error(
            "pipeline_file_missing",
            batch_id=batch_id,
            path=upload_meta.path,
        )
        _emit_error(batch_id, exc)
        return

    raw_upload = RawUpload(
        upload_id=upload_id,
        product_id=upload_meta.product,
        filename=upload_meta.filename,
        file_bytes=file_bytes,
        wave=upload_meta.wave,
        country=upload_meta.country,
    )

    # Single event loop for phases 1-4 + phase 5 + finish.
    # One PostgresStore for the entire invocation — prevents multiple
    # asyncpg pools from being created and torn down in the same loop.
    async def _run_all_and_finish() -> None:
        pg = PostgresStore(POSTGRES_ASYNC_URL)
        try:
            await pg.ensure_schema()
            # Transition status to "processing" so /progress reflects reality.
            await _update_batch_status_sync(batch_id, "processing", pg)

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

                # Phase 1 (ingest) — pauses before retrieve (phase 2)
                state = await graph.ainvoke(
                    initial, config=thread_config,
                )

                # Extract and persist gate 1 data
                phase1_rows = _extract_gate1_rows(state)
                RedisPubSub.persist_gate_data_sync(
                    REDIS_URL, batch_id, "phase1_atoms", phase1_rows
                )
                await _update_batch_status_sync(batch_id, "gate_1", pg)
                _write_batch_state(batch_id, status="gate_1")

                # Publish gate 1 event and exit
                gate_event = PhaseGateEvent(
                    batch_id=batch_id,
                    gate=1,
                    phase_name="Ingestion",
                    atoms_count=len(phase1_rows),
                )
                RedisPubSub.publish_sync(REDIS_URL, gate_event)
                log.info("gate_1_published", batch_id=batch_id, atoms_count=len(phase1_rows))
        finally:
            await pg.dispose()

    try:
        asyncio.run(_run_all_and_finish())
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
            # Write error status to PostgreSQL
            asyncio.run(_update_batch_error(batch_id))
            return
