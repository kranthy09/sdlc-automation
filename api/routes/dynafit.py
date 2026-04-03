"""
REQFIT API routes — thin dispatchers only.

Rule: zero business logic here. Routes validate input, persist minimal
metadata, dispatch to Celery, and return. All computation lives in
modules/dynafit/ and is invoked by api/workers/tasks.py (Session B).

State store:
  Uploads and batch metadata are persisted to PostgreSQL via
  platform/storage/postgres.py (durable). In-flight progress (phases,
  classifications, review items) are cached in Redis (transient).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from api.models import (
    AtomJourney,
    AutoApprovedItem,
    BatchHistoryItem,
    BatchHistoryResponse,
    BatchSummary,
    BatchView,
    EvidenceItem,
    GateAtomsResponse,
    JourneyResponse,
    PhaseProgressItem,
    PriorFitmentItem,
    ProceedResponse,
    ProgressClassificationItem,
    ProgressResponse,
    PublicResultsResponse,
    ResultItem,
    ResultsResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewItem,
    ReviewQueueResponse,
    RunRequest,
    RunResponse,
    UploadResponse,
)
from platform.ingestion import ArtifactStore
from platform.parsers.format_detector import detect_format
from platform.schemas.errors import UnsupportedFormatError
from platform.storage.postgres import PostgresStore, UploadRecord
from platform.storage.redis_pub import RedisPubSub

log = structlog.get_logger(__name__)

router = APIRouter(tags=["dynafit"])
public_router = APIRouter(tags=["public"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/dynafit_uploads"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _get_pg(request: Request) -> PostgresStore:
    """Retrieve the PostgresStore attached at startup."""
    return request.app.state.pg_store  # type: ignore[no-any-return]


def _dispatch(batch_id: str, upload_id: str, config: dict[str, Any]) -> None:
    """Enqueue the pipeline task. Upload metadata is included so the Celery
    worker (separate process) can reconstruct RawUpload without shared
    memory."""
    try:
        # TODO: always import at the top.
        from api.workers.tasks import run_dynafit_pipeline  # noqa: PLC0415

        # Phase state is durably persisted to the batch Redis hash by
        # RedisPubSub.publish(), so no countdown delay is needed —
        # the WebSocket catch-up replays persisted state on connect.
        run_dynafit_pipeline.delay(batch_id, upload_id, config)
    except ImportError:
        log.warning("celery_not_ready", batch_id=batch_id)


def _dispatch_resume(batch_id: str, overrides: dict[str, Any]) -> None:
    """Enqueue a resume-only run for Phase 5 after HITL review completes."""
    try:
        from api.workers.tasks import run_dynafit_pipeline  # noqa: PLC0415

        run_dynafit_pipeline.delay(
            batch_id, "", {"_resume": True, "_overrides": overrides})
    except ImportError:
        log.warning("celery_not_ready_resume", batch_id=batch_id)


def _build_overrides(review_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert stored review decisions into the format Phase 5 expects.

    Returns a dict keyed by atom_id:
      - None  → human approved the AI classification (keep original)
      - dict  → human override: {classification, rationale, consultant}
    """
    overrides: dict[str, Any] = {}
    for item in review_items:
        atom_id = item["atom_id"]
        is_override = item.get("decision") == "OVERRIDE" and item.get(
            "override_classification")
        if is_override:
            reviewer = item.get("reviewer", "unknown")
            overrides[atom_id] = {
                "classification": item["override_classification"],
                "rationale": f"Reviewer override by {reviewer}",
                "consultant": item.get("reviewer"),
            }
        else:
            # APPROVE or unreviewed — keep AI classification unchanged
            overrides[atom_id] = None
    return overrides


async def _load_review_items_from_db(
    request: Request, batch_id: str
) -> list[dict[str, Any]]:
    """Load HITL review decisions from PostgreSQL.

    Review items are durable and stored in PostgreSQL. Returns them as a list
    of dicts. Falls back gracefully to empty list if no items or DB error.
    """
    pg = _get_pg(request)
    try:
        db_items = await pg.get_review_items_by_batch(batch_id)
        if db_items:
            # Convert ReviewItemRecord to dict format for API compatibility
            items = [
                {
                    "atom_id": item.atom_id,
                    "ai_classification": item.ai_classification,
                    "ai_confidence": item.ai_confidence,
                    "decision": item.decision,
                    "override_classification": item.override_classification,
                    "reviewer": item.reviewer,
                    "reviewed": item.reviewed,
                    "requirement_text": item.requirement_text,
                    "ai_rationale": item.ai_rationale,
                    "review_reason": item.review_reason,
                    "module": item.module,
                    "evidence": item.evidence or {},
                    "config_steps": item.config_steps,
                    "gap_description": item.gap_description,
                    "configuration_steps": item.configuration_steps,
                    "dev_effort": item.dev_effort,
                    "gap_type": item.gap_type,
                }
                for item in db_items
            ]
            log.debug(
                "review_items_loaded_from_postgres",
                batch_id=batch_id,
                count=len(db_items),
            )
            return items
    except Exception as exc:
        log.warning(
            "review_items_postgres_load_failed",
            batch_id=batch_id,
            error=str(exc),
        )
    # Return empty list on error or no items
    return []


def _load_journey_from_redis(
    batch_id: str,
) -> list[dict[str, Any]]:
    """Load journey traceability data from Redis (lazy-load).

    Journey is a potentially large JSON blob of per-atom processing history.
    Load it only when explicitly needed (for /journey endpoint).

    Returns empty list if journey is unavailable.
    """
    data = RedisPubSub.read_batch_state_sync(REDIS_URL, batch_id)
    if not data or "journey" not in data:
        return []

    try:
        return json.loads(data["journey"])
    except json.JSONDecodeError:
        return []


def _load_transient_from_redis(
    batch_id: str,
    include_journey: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Load transient in-flight state from Redis.

    Returns: (phases, classifications, journey, auto_approved, review_items)

    Durable batch state (status, summary, report_path, completed_at)
    lives in PostgreSQL. Redis stores only ephemeral phase progress and
    live classifications that don't persist across process restarts.

    review_items in Redis carries the full rich payload (evidence, rationale,
    requirement_text, etc.) that PostgreSQL does not store. Callers must merge
    PG decision fields on top of these Redis items.

    Args:
        batch_id:        Batch identifier.
        include_journey: If False, skip loading journey (optimization for endpoints
                        that don't need per-atom traceability data).

    Note: results are NOT loaded or cached. They are stored in PostgreSQL.
    """
    data = RedisPubSub.read_batch_state_sync(REDIS_URL, batch_id)

    phases: dict[str, Any] = {}
    classifications: list[dict[str, Any]] = []
    journey: list[dict[str, Any]] = []
    auto_approved: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []

    if not data:
        return phases, classifications, journey, auto_approved, review_items

    # Load phase progress (in-flight only, not persisted to DB)
    if "phases" in data:
        try:
            phases = json.loads(data["phases"])
        except json.JSONDecodeError:
            pass

    if "classifications" in data:
        try:
            classifications = json.loads(data["classifications"])
        except json.JSONDecodeError:
            pass

    # Load journey traceability only if requested (large JSON, optional)
    if include_journey and "journey" in data:
        try:
            journey = json.loads(data["journey"])
        except json.JSONDecodeError:
            pass

    # Load auto-approved items if any
    if "auto_approved" in data:
        try:
            auto_approved = json.loads(data["auto_approved"])
        except json.JSONDecodeError:
            pass

    # Load rich review items (evidence, rationale, requirement_text, etc.)
    if "review_items" in data:
        try:
            review_items = json.loads(data["review_items"])
        except json.JSONDecodeError:
            pass

    return phases, classifications, journey, auto_approved, review_items


async def _get_batch(
    request: Request,
    batch_id: str,
    include_journey: bool = True,
) -> BatchView:
    """Load batch from PostgreSQL (source of truth) + Redis (transient state).

    Returns typed BatchView with durable fields from PostgreSQL and transient
    fields from Redis. Raises HTTPException 404 if batch not found.

    Args:
        request:          FastAPI request context.
        batch_id:         Batch identifier.
        include_journey:  If False, skip loading journey JSON from Redis (optimization
                         for endpoints that don't need per-atom traceability).
                         Defaults to True for backward compatibility.
    """
    pg = _get_pg(request)

    # Source of truth: PostgreSQL
    db_batch = await pg.get_batch_by_id(batch_id)
    if db_batch is None:
        raise HTTPException(
            status_code=404,
            detail=f"batch_id {batch_id!r} not found",
        )

    # Fetch upload metadata (for upload_filename, detected_format, etc.)
    upload = await pg.get_upload_by_id(db_batch.upload_id)
    upload_filename = upload.filename if upload else ""

    # Load rich review items from Redis (evidence, rationale, requirement_text, etc.)
    # and decision tracking from PostgreSQL; merge PG decisions onto Redis items.
    phases, classifications, journey, auto_approved, redis_review_items = (
        _load_transient_from_redis(batch_id, include_journey=include_journey)
    )

    if redis_review_items:
        # Redis has the full rich payload — overlay PG decision fields on top
        pg_decisions: dict[str, dict[str, Any]] = {}
        for pg_item in await _load_review_items_from_db(request, batch_id):
            pg_decisions[pg_item["atom_id"]] = pg_item
        review_items: list[dict[str, Any]] = [
            {**item, **{k: v for k, v in pg_decisions.get(item["atom_id"], {}).items()
                        if k in ("ai_classification", "ai_confidence", "decision", "override_classification", "reviewer", "reviewed")}}
            for item in redis_review_items
        ]
    else:
        # Redis cache expired — fall back to PostgreSQL (minimal, no evidence)
        review_items = await _load_review_items_from_db(request, batch_id)

    log.debug(
        "batch_loaded",
        batch_id=batch_id,
        from_db=True,
        journey_loaded=include_journey,
    )
    return BatchView(
        batch_id=db_batch.batch_id,
        upload_id=db_batch.upload_id,
        upload_filename=upload_filename,
        product=db_batch.product_id,
        country=db_batch.country,
        wave=db_batch.wave,
        status=db_batch.status,
        summary=db_batch.summary or {"total": 0, "fit": 0, "partial_fit": 0, "gap": 0},
        report_path=db_batch.report_path,
        created_at=db_batch.created_at.isoformat(),
        completed_at=db_batch.completed_at.isoformat() if db_batch.completed_at else None,
        phases=phases,
        classifications=classifications,
        journey=journey,
        review_items=review_items,
        auto_approved=auto_approved,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# 1. Upload
# ---------------------------------------------------------------------------


@router.post("/upload", status_code=201)
async def upload_file(
    request: Request,
    file: UploadFile,
    product: str = Form(...),
    country: str = Form(...),
    wave: int = Form(...),
) -> UploadResponse:
    pg = _get_pg(request)

    filename = file.filename or "upload"
    content = await file.read()
    content_hash = hashlib.sha256(content).hexdigest()

    # O(1) duplicate check via indexed content_hash column
    existing = await pg.get_upload_by_hash(content_hash)
    if existing is not None:
        log.info(
            "upload_duplicate_detected",
            existing_id=existing.upload_id,
        )
        return UploadResponse(
            upload_id=existing.upload_id,
            filename=existing.filename,
            size_bytes=existing.size_bytes,
            detected_format=existing.detected_format.upper(),
            status="already_exists",
        )

    upload_id = f"upl_{uuid.uuid4().hex[:8]}"
    dest_dir = UPLOAD_DIR / upload_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    dest_path.write_bytes(content)

    try:
        fmt_result = detect_format(dest_path)
    except UnsupportedFormatError as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422, detail=str(exc),
        ) from exc

    record = UploadRecord(
        upload_id=upload_id,
        product_id=product,
        filename=filename,
        wave=wave,
        country=country,
        status="pending",
        created_at=datetime.now(UTC),
        content_hash=content_hash,
        path=str(dest_path),
        size_bytes=len(content),
        detected_format=fmt_result.format,
    )
    await pg.save_upload(record)

    log.info(
        "upload_complete",
        upload_id=upload_id,
        fmt=fmt_result.format,
    )
    return UploadResponse(
        upload_id=upload_id,
        filename=filename,
        size_bytes=len(content),
        detected_format=fmt_result.format.upper(),
    )


# ---------------------------------------------------------------------------
# 2. Start pipeline
# ---------------------------------------------------------------------------


@router.post("/d365_fo/dynafit/run", status_code=202)
async def run_pipeline(
    request: Request,
    body: RunRequest,
) -> RunResponse:
    pg = _get_pg(request)

    up = await pg.get_upload_by_id(body.upload_id)
    if up is None:
        raise HTTPException(
            status_code=404,
            detail=f"upload_id {body.upload_id!r} not found",
        )

    batch_id = f"bat_{uuid.uuid4().hex[:8]}"
    created_at_dt = datetime.now(UTC)
    created_at_str = created_at_dt.isoformat()

    # Write to PostgreSQL (source of truth)
    from platform.storage.postgres import BatchRecord  # noqa: PLC0415
    from api.models import BatchSummary, UploadMetadata, PipelineConfig  # noqa: PLC0415

    initial_summary = BatchSummary(
        total=0, fit=0, partial_fit=0, gap=0
    )
    batch_record = BatchRecord(
        batch_id=batch_id,
        upload_id=body.upload_id,
        product_id=up.product_id,
        country=up.country,
        wave=up.wave,
        status="queued",
        created_at=created_at_dt,
        summary=initial_summary.model_dump(),
    )
    await pg.save_batch(batch_record)

    # Register in Redis for WebSocket progress tracking
    RedisPubSub.register_batch_sync(
        REDIS_URL, batch_id, created_at_str,
    )

    # Build typed configuration for Celery worker
    upload_meta = UploadMetadata(
        upload_id=up.upload_id,
        filename=up.filename,
        path=up.path,
        product=up.product_id,
        country=up.country,
        wave=up.wave,
        size_bytes=up.size_bytes,
        detected_format=up.detected_format,
        content_hash=up.content_hash,
    )
    config = PipelineConfig(
        config_overrides=body.config_overrides,
        upload_meta=upload_meta,
    )

    # Convert to dict for Celery (which expects JSON-serializable format)
    config_dict = config.model_dump()
    _dispatch(batch_id, body.upload_id, config_dict)
    log.info(
        "pipeline_queued",
        batch_id=batch_id,
        upload_id=body.upload_id,
    )
    return RunResponse(
        batch_id=batch_id,
        upload_id=body.upload_id,
        websocket_url=f"/api/v1/ws/progress/{batch_id}",
    )


# ---------------------------------------------------------------------------
# 3. Batch history (declared before /{batch_id}/... to avoid routing ambiguity)
# ---------------------------------------------------------------------------


def _to_batch_dict(db_batch: Any) -> dict[str, Any]:
    """Convert a postgres.BatchRecord to the batch dict format.

    Includes durable fields from the DB record. Transient state from Redis
    must be loaded separately and merged by the caller.
    """
    return {
        "batch_id": db_batch.batch_id,
        "upload_id": db_batch.upload_id,
        "upload_filename": db_batch.upload_filename,
        "product": db_batch.product_id,
        "country": db_batch.country,
        "wave": db_batch.wave,
        "status": db_batch.status,
        "summary": (
            db_batch.summary
            or {"total": 0, "fit": 0, "partial_fit": 0, "gap": 0}
        ),
        "created_at": db_batch.created_at.isoformat(),
        "completed_at": (
            db_batch.completed_at.isoformat()
            if db_batch.completed_at else None
        ),
        "report_path": db_batch.report_path,
    }


@router.get("/d365_fo/dynafit/batches")
async def list_batches(
    request: Request,
    country: str | None = None,
    wave: int | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 10,
) -> BatchHistoryResponse:
    pg = _get_pg(request)

    # Get total count for pagination (DB-level COUNT)
    total = await pg.count_batches(
        country=country, wave=wave, status=status
    )

    # Calculate offset and fetch this page only (DB-level OFFSET/LIMIT)
    offset = (page - 1) * limit
    db_batches = await pg.list_batches(
        country=country, wave=wave, status=status,
        offset=offset, limit=limit
    )

    # Convert DB records to API response items
    items: list[BatchHistoryItem] = []
    for db_batch in db_batches:
        items.append(
            BatchHistoryItem(
                batch_id=db_batch.batch_id,
                upload_filename=db_batch.upload_filename,
                product=db_batch.product_id,
                country=db_batch.country,
                wave=db_batch.wave,
                status=db_batch.status,
                summary=BatchSummary(**(
                    db_batch.summary
                    or {"total": 0, "fit": 0, "partial_fit": 0, "gap": 0}
                )),
                created_at=db_batch.created_at.isoformat(),
                completed_at=(
                    db_batch.completed_at.isoformat()
                    if db_batch.completed_at else None
                ),
            )
        )

    return BatchHistoryResponse(
        batches=items,
        total=total,
        page=page,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# 4. Results
# ---------------------------------------------------------------------------


_SORTABLE_FIELDS = frozenset(
    {"confidence", "module", "classification", "atom_id"})


@router.get("/d365_fo/dynafit/{batch_id}/results")
async def get_results(
    request: Request,
    batch_id: str,
    classification: str | None = None,
    module: str | None = None,
    sort: str = "confidence",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    limit: int = 25,
) -> ResultsResponse:
    pg = _get_pg(request)
    batch = await _get_batch(request, batch_id)

    # DB-level count with optional filters
    total = await pg.count_results_by_batch(
        batch_id,
        classification=classification,
        module=module,
    )

    if total == 0:
        return ResultsResponse(
            batch_id=batch_id,
            status=batch.status,
            total=0,
            page=page,
            limit=limit,
            results=[],
            summary=BatchSummary(**batch.summary),
        )

    # Allowlist sort fields to prevent injection
    sort_key = sort if sort in _SORTABLE_FIELDS else "confidence"
    order_str = "desc" if order == "desc" else "asc"

    # DB-level pagination and filtering
    offset = (page - 1) * limit
    db_results = await pg.get_results_by_batch(
        batch_id,
        classification=classification,
        module=module,
        sort=sort_key,
        order=order_str,
        offset=offset,
        limit=limit,
    )

    # Index journey data by atom_id for optional attachment (eliminates N+1)
    journey_by_atom: dict[str, dict[str, Any]] = {}
    if batch.journey:
        journey_by_atom = {
            j["atom_id"]: j for j in batch.journey
        }

    # Convert database records to API response items
    result_items: list[ResultItem] = []
    for db_result in db_results:
        item = ResultItem(
            atom_id=db_result.atom_id,
            requirement_text=db_result.requirement_text,
            classification=db_result.classification,
            confidence=db_result.confidence,
            module=db_result.module,
            country=db_result.country,
            wave=db_result.wave,
            rationale=db_result.rationale,
            reviewer_override=db_result.reviewer_override,
            d365_capability=db_result.d365_capability,
            d365_navigation=db_result.d365_navigation,
            config_steps=db_result.config_steps,
            gap_description=db_result.gap_description,
            configuration_steps=db_result.configuration_steps,
            dev_effort=db_result.dev_effort,
            gap_type=db_result.gap_type,
        )

        # Attach evidence if available
        if db_result.evidence:
            evidence_dict = db_result.evidence
            item.evidence = EvidenceItem(
                top_capability_score=evidence_dict.get("top_capability_score", 0.0),
                retrieval_confidence=evidence_dict.get("retrieval_confidence", "LOW"),
                prior_fitments=[
                    PriorFitmentItem(**pf)
                    for pf in evidence_dict.get("prior_fitments", [])
                ],
            )

        # Attach journey data if available (optional traceability)
        j = journey_by_atom.get(db_result.atom_id)
        if j:
            item.journey = AtomJourney(**j)

        result_items.append(item)

    return ResultsResponse(
        batch_id=batch_id,
        status=batch.status,
        total=total,
        page=page,
        limit=limit,
        results=result_items,
        summary=BatchSummary(**batch.summary),
    )


# ---------------------------------------------------------------------------
# 4b. Journey (per-atom pipeline traceability)
# ---------------------------------------------------------------------------


@router.get("/d365_fo/dynafit/{batch_id}/journey")
async def get_journey(
    request: Request,
    batch_id: str,
    atom_id: str | None = None,
) -> JourneyResponse:
    batch = await _get_batch(request, batch_id)
    if batch.status not in ("complete", "review_required"):
        raise HTTPException(
            status_code=409,
            detail="Journey data available only for completed batches",
        )
    journey = batch.journey
    if atom_id:
        journey = [j for j in journey if j["atom_id"] == atom_id]
    return JourneyResponse(
        batch_id=batch_id,
        atoms=[AtomJourney(**j) for j in journey],
    )


# ---------------------------------------------------------------------------
# 4c. Pipeline progress (durable phase state from Redis hash)
# ---------------------------------------------------------------------------

PHASE_NAMES = ["Ingestion", "RAG", "Matching", "Classification", "Validation"]


@router.get("/d365_fo/dynafit/{batch_id}/progress")
async def get_progress(request: Request, batch_id: str) -> ProgressResponse:
    batch = await _get_batch(request, batch_id, include_journey=False)

    # Read persisted phase states + classifications from Redis hash
    persisted: dict[str, dict[str, Any]] = {}
    persisted_cls: list[dict[str, Any]] = []
    data = RedisPubSub.read_batch_state_sync(REDIS_URL, batch_id)
    if data.get("phases"):
        try:
            persisted = json.loads(data["phases"])
        except json.JSONDecodeError:
            pass
    if data.get("classifications"):
        try:
            persisted_cls = json.loads(data["classifications"])
        except json.JSONDecodeError:
            pass

    # Build 5-phase list, merging persisted data with defaults
    phases: list[PhaseProgressItem] = []
    for i in range(1, 6):
        key = str(i)
        if key in persisted:
            p = persisted[key]
            phases.append(
                PhaseProgressItem(
                    phase=i,
                    phase_name=p.get("phase_name", PHASE_NAMES[i - 1]),
                    status=p.get("status", "pending"),
                    current_step=p.get("current_step"),
                    progress_pct=p.get("progress_pct", 0),
                    atoms_produced=p.get("atoms_produced", 0),
                    atoms_validated=p.get("atoms_validated", 0),
                    atoms_flagged=p.get("atoms_flagged", 0),
                    latency_ms=p.get("latency_ms"),
                )
            )
        else:
            phases.append(
                PhaseProgressItem(
                    phase=i,
                    phase_name=PHASE_NAMES[i - 1],
                )
            )

    classifications = [
        ProgressClassificationItem(
            atom_id=c["atom_id"],
            classification=c["classification"],
            confidence=c["confidence"],
            requirement_text=c.get(
                "requirement_text", ""
            ),
            module=c.get("module", ""),
            rationale=c.get("rationale", ""),
            d365_capability=c.get(
                "d365_capability", ""
            ),
            d365_navigation=c.get(
                "d365_navigation", ""
            ),
            journey=c.get("journey"),
        )
        for c in persisted_cls
    ]

    return ProgressResponse(
        batch_id=batch_id,
        status=batch.status,
        phases=phases,
        classifications=classifications,
    )


# ---------------------------------------------------------------------------
# 5. Review queue
# ---------------------------------------------------------------------------


@router.get("/d365_fo/dynafit/{batch_id}/review")
async def get_review_queue(
    request: Request, batch_id: str
) -> ReviewQueueResponse:
    batch = await _get_batch(request, batch_id, include_journey=False)
    return ReviewQueueResponse(
        batch_id=batch_id,
        status=batch.status,
        items=[ReviewItem(**i) for i in batch.review_items],
        auto_approved=[AutoApprovedItem(**i) for i in batch.auto_approved],
    )


# ---------------------------------------------------------------------------
# 6a. Complete review — resume pipeline after all HITL items resolved
# ---------------------------------------------------------------------------


@router.post("/d365_fo/dynafit/{batch_id}/review/complete", status_code=202)
async def complete_review(
    request: Request, batch_id: str
) -> dict[str, str]:
    batch = await _get_batch(request, batch_id, include_journey=False)
    overrides = _build_overrides(batch.review_items)
    # Write status transition immediately — before dispatching Celery task — so
    # that any GET /progress poll that arrives after this returns "resuming", not
    # "review_required".  Without this, the progress page sees review_required
    # and bounces the user back to the review queue before the worker runs.
    RedisPubSub.write_batch_state_sync(REDIS_URL, batch_id, status="resuming")
    _dispatch_resume(batch_id, overrides)
    log.info(
        "review_complete_dispatched",
        batch_id=batch_id,
        override_count=len(overrides),
    )
    return {"batch_id": batch_id, "status": "resuming"}


# ---------------------------------------------------------------------------
# 6b. Submit individual review decision
# ---------------------------------------------------------------------------


@router.post("/d365_fo/dynafit/{batch_id}/review/{atom_id}")
async def submit_review(
    request: Request,
    batch_id: str,
    atom_id: str,
    body: ReviewDecisionRequest,
) -> ReviewDecisionResponse:
    pg = _get_pg(request)
    batch = await _get_batch(request, batch_id, include_journey=False)
    items = batch.review_items

    if not items:
        raise HTTPException(
            status_code=409,
            detail="Batch is not in review state or has no review items",
        )

    item = next((i for i in items if i["atom_id"] == atom_id), None)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"atom_id {atom_id!r} not in review queue",
        )
    if body.decision == "OVERRIDE" and not body.override_classification:
        raise HTTPException(
            status_code=422,
            detail="override_classification required for OVERRIDE",
        )

    item["reviewed"] = True
    item["decision"] = body.decision
    item["reviewer"] = body.reviewer
    item["override_classification"] = body.override_classification

    # Write decision to PostgreSQL (durable) and Redis (transient)
    try:
        await pg.save_review_decision(
            batch_id=batch_id,
            atom_id=atom_id,
            ai_classification=item.get("ai_classification", ""),
            decision=body.decision,
            override_classification=body.override_classification,
            reviewer=body.reviewer,
        )
    except Exception as exc:
        log.error(
            "review_decision_postgres_write_failed",
            batch_id=batch_id,
            atom_id=atom_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to save review decision",
        ) from exc

    # Also persist to Redis for in-process visibility
    RedisPubSub.write_batch_state_sync(
        REDIS_URL, batch_id,
        review_items=json.dumps(batch.review_items),
    )

    final = (
        body.override_classification if body.decision == "OVERRIDE" else item[
            "ai_classification"]
    )
    remaining = sum(1 for i in items if not i.get("reviewed", False))

    log.info(
        "review_submitted",
        batch_id=batch_id,
        atom_id=atom_id,
        decision=body.decision,
    )
    return ReviewDecisionResponse(
        atom_id=atom_id,
        final_classification=final,
        reviewer_override=body.decision == "OVERRIDE",
        remaining_reviews=remaining,
    )


# ---------------------------------------------------------------------------
# 6b. Phase gates (analyst approval to proceed)
# ---------------------------------------------------------------------------


def _dispatch_proceed(batch_id: str, gate: int) -> None:
    """Dispatch a Celery task to proceed from a phase gate."""
    from api.workers.tasks import run_dynafit_pipeline

    run_dynafit_pipeline.delay(batch_id, "", {"_proceed_from_gate": gate})


@router.post("/d365_fo/dynafit/{batch_id}/proceed", status_code=202)
async def proceed_gate(
    request: Request, batch_id: str,
) -> ProceedResponse:
    """Analyst approves proceeding from a phase gate.

    The batch must be in a gate_N status. Dispatches a Celery task
    to resume from that gate and run the next phase.
    """
    batch = await _get_batch(request, batch_id, include_journey=False)

    # Extract gate number from status (e.g., "gate_1" -> 1)
    if not batch.status or not batch.status.startswith("gate_"):
        raise HTTPException(
            status_code=400,
            detail=f"Batch not at a gate (status: {batch.status})",
        )

    try:
        gate = int(batch.status.split("_")[1])
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid gate status: {batch.status}",
        ) from None

    # Write "processing" to Redis immediately to prevent race conditions
    RedisPubSub.write_batch_state_sync(REDIS_URL, batch_id, status="processing")

    # Dispatch Celery task with gate proceeding config
    try:
        _dispatch_proceed(batch_id, gate)
    except Exception as exc:
        log.error(
            "gate_proceed_dispatch_failed",
            batch_id=batch_id,
            gate=gate,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to dispatch gate proceed task",
        ) from exc

    log.info(
        "gate_proceed_requested",
        batch_id=batch_id,
        gate=gate,
        next_phase=gate + 1,
    )
    return ProceedResponse(batch_id=batch_id, next_phase=gate + 1)


@router.get("/d365_fo/dynafit/{batch_id}/gate/{gate}/atoms")
async def get_gate_atoms(
    request: Request,
    batch_id: str,
    gate: int,
) -> GateAtomsResponse:
    """Retrieve summary data for a phase gate.

    Returns the atoms/contexts/matches produced by the phase that paused
    at this gate, for analyst review before proceeding.

    Gate 1: ingestion atoms (phase1_atoms)
    Gate 2: retrieval contexts (phase2_contexts)
    Gate 3: matching results (phase3_matches)
    Gate 4: classifications (already-streamed, from classifications field)
    """
    batch = await _get_batch(request, batch_id, include_journey=False)

    if gate < 1 or gate > 4:
        raise HTTPException(
            status_code=400,
            detail="Gate must be 1-4",
        )

    # Read gate data from Redis
    batch_state = RedisPubSub.read_batch_state_sync(REDIS_URL, batch_id)

    field_map = {
        1: "phase1_atoms",
        2: "phase2_contexts",
        3: "phase3_matches",
        4: "classifications",  # classifications is a JSON list, not hash field
    }
    field = field_map.get(gate, "")

    rows: list[dict[str, Any]] = []
    if gate == 4:
        # Gate 4 uses the classifications list field (different structure)
        if "classifications" in batch_state:
            try:
                rows = json.loads(batch_state["classifications"])
            except (json.JSONDecodeError, ValueError):
                rows = []
    else:
        # Gates 1-3 use hash fields
        if field in batch_state:
            try:
                rows = json.loads(batch_state[field])
            except (json.JSONDecodeError, ValueError):
                rows = []

    # Backwards-compatible metadata enrichment for Phase 2 and 3.
    # Older batches processed before the metadata fields were added to the
    # gate extraction helpers will have rows missing module/country/intent/priority.
    # Cross-reference phase1_atoms (always present, always has full metadata)
    # and merge any missing atom-level fields into the Phase 2/3 rows.
    if gate in (2, 3) and rows:
        first = rows[0]
        missing_meta = not first.get("module") and not first.get("country")
        if missing_meta and "phase1_atoms" in batch_state:
            try:
                phase1_rows: list[dict[str, Any]] = json.loads(batch_state["phase1_atoms"])
                meta_lookup: dict[str, dict[str, Any]] = {
                    r["atom_id"]: r for r in phase1_rows
                }
                for row in rows:
                    p1 = meta_lookup.get(row.get("atom_id", ""), {})
                    row.setdefault("module", p1.get("module", ""))
                    row.setdefault("country", p1.get("country", ""))
                    row.setdefault("intent", p1.get("intent", ""))
                    row.setdefault("priority", p1.get("priority", ""))
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

    log.info(
        "gate_atoms_retrieved",
        batch_id=batch_id,
        gate=gate,
        rows_count=len(rows),
    )
    return GateAtomsResponse(batch_id=batch_id, gate=gate, rows=rows)


# ---------------------------------------------------------------------------
# 7. Download report
# ---------------------------------------------------------------------------


@router.get("/d365_fo/dynafit/{batch_id}/report")
async def download_report(
    request: Request,
    batch_id: str,
    file: str | None = None,
) -> Response:
    """Download report CSV files.

    If ``file`` is omitted, returns a JSON manifest listing
    available CSVs. If ``file`` is specified, returns that
    individual CSV. No ZIP — stdlib csv only (project rule).
    """
    batch = await _get_batch(request, batch_id, include_journey=False)
    report_path = batch.report_path
    if not report_path or not Path(report_path).exists():
        raise HTTPException(
            status_code=404,
            detail="Report not yet generated",
        )

    report_dir = Path(report_path)

    # report_path is a directory of CSVs from Phase 5
    if report_dir.is_dir():
        csvs = sorted(report_dir.glob("*.csv"))
        if file:
            target = report_dir / file
            if not target.exists() or target not in csvs:
                raise HTTPException(
                    status_code=404,
                    detail=f"File {file!r} not found",
                )
            return FileResponse(
                path=str(target),
                media_type="text/csv",
                filename=file,
            )
        # Return manifest of available CSV files
        return JSONResponse(
            {"files": [f.name for f in csvs]},
        )

    # Fallback: single file
    return FileResponse(
        path=report_path,
        media_type="text/csv",
        filename=f"fdd_report_{batch_id}.csv",
    )


# ---------------------------------------------------------------------------
# 7b. Artifact retrieval (multimodal ingestion output — Phase 1)
# ---------------------------------------------------------------------------


def _get_artifact_store_path_from_redis(batch_id: str) -> str | None:
    """Load artifact_store_batch_path from Redis batch hash.

    Reads from dedicated field (not nested JSON).
    Returns the path string or None if not found.
    """
    try:
        from platform.storage.redis_pub import get_redis_client  # noqa: PLC0415

        redis = get_redis_client()
        raw = redis.hget(f"batch:{batch_id}", "artifact_store_batch_path")
        if raw:
            return raw.decode() if isinstance(raw, bytes) else raw
    except Exception as exc:
        log.warning(
            "redis_artifact_path_load_failed",
            batch_id=batch_id,
            error=str(exc),
        )
    return None


@router.get("/d365_fo/dynafit/{batch_id}/artifacts")
async def list_artifacts(
    request: Request,
    batch_id: str,
) -> JSONResponse:
    """List all artifacts (tables, images) stored for this batch.

    Returns metadata for all artifacts: artifact_id, artifact_type,
    storage_path, page_no, section_path.

    Requires artifact_store_batch_path to exist in Redis batch state
    (populated by Phase 1 ingestion).
    """
    # Validate batch exists
    await _get_batch(request, batch_id, include_journey=False)

    artifact_path = _get_artifact_store_path_from_redis(batch_id)
    if not artifact_path:
        raise HTTPException(
            status_code=404,
            detail="Artifacts not available for this batch (Phase 1 unified pipeline may not have run)",
        )

    try:
        # Reconstruct artifact references from filesystem
        # For now, return empty list as a safe default
        # In production, walk the artifact directory and build metadata
        artifacts = []

        batch_path = Path(artifact_path)
        if batch_path.exists() and batch_path.is_dir():
            # Walk artifact types: TABLE_IMAGE, TABLE_DATAFRAME, FIGURE_IMAGE
            for artifact_type_dir in batch_path.iterdir():
                if not artifact_type_dir.is_dir():
                    continue
                artifact_type = artifact_type_dir.name
                for artifact_file in artifact_type_dir.iterdir():
                    if artifact_file.is_file():
                        artifacts.append({
                            "artifact_id": artifact_file.stem,
                            "artifact_type": artifact_type,
                            "filename": artifact_file.name,
                            "storage_path": str(artifact_file),
                        })

        return JSONResponse({"artifacts": artifacts})

    except Exception as exc:
        log.error(
            "artifact_list_failed",
            batch_id=batch_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to list artifacts",
        ) from exc


@router.get("/d365_fo/dynafit/{batch_id}/artifacts/{artifact_id}")
async def retrieve_artifact(
    request: Request,
    batch_id: str,
    artifact_id: str,
) -> FileResponse:
    """Retrieve a single artifact file (image or dataframe).

    Returns the file with appropriate Content-Type and cache headers.

    Args:
        batch_id:     Batch identifier.
        artifact_id:  Artifact identifier (e.g., hash prefix).

    Returns:
        FileResponse with Cache-Control: public, max-age=86400.
    """
    # Validate batch exists
    await _get_batch(request, batch_id, include_journey=False)

    artifact_path = _get_artifact_store_path_from_redis(batch_id)
    if not artifact_path:
        raise HTTPException(
            status_code=404,
            detail="Artifacts not available for this batch",
        )

    try:
        # Use ArtifactStore to safely retrieve the artifact
        # For now, search in the batch directory by artifact_id
        batch_path = Path(artifact_path)

        if not batch_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Batch artifact directory not found: {artifact_path}",
            )

        # Search for the artifact across all type subdirectories
        artifact_file: Path | None = None
        for artifact_type_dir in batch_path.iterdir():
            if not artifact_type_dir.is_dir():
                continue
            candidate = artifact_type_dir / f"{artifact_id}.png"
            if candidate.exists():
                artifact_file = candidate
                break
            # Also try .parquet for TABLE_DATAFRAME
            candidate = artifact_type_dir / f"{artifact_id}.parquet"
            if candidate.exists():
                artifact_file = candidate
                break

        if not artifact_file or not artifact_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Artifact {artifact_id} not found",
            )

        # Determine MIME type
        suffix = artifact_file.suffix.lower()
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".parquet": "application/octet-stream",
        }.get(suffix, "application/octet-stream")

        log.debug(
            "artifact_retrieved",
            batch_id=batch_id,
            artifact_id=artifact_id,
            media_type=media_type,
        )

        # Return with cache headers
        return FileResponse(
            path=str(artifact_file),
            media_type=media_type,
            filename=artifact_file.name,
            headers={
                "Cache-Control": "public, max-age=86400",
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        log.error(
            "artifact_retrieval_failed",
            batch_id=batch_id,
            artifact_id=artifact_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve artifact",
        ) from exc


# ---------------------------------------------------------------------------
# 8. Public results (shareable read-only — no product prefix)
# ---------------------------------------------------------------------------


@public_router.get("/batches/{batch_id}/results")
async def get_public_results(
    request: Request, batch_id: str
) -> PublicResultsResponse:
    pg = _get_pg(request)
    batch = await _get_batch(request, batch_id, include_journey=False)

    # Fetch all results from PostgreSQL (no pagination for public results)
    db_results = await pg.get_results_by_batch(
        batch_id,
        offset=0,
        limit=10000,  # Reasonable upper bound for batch atom count
    )

    # Convert database records to API response items
    result_items: list[ResultItem] = []
    for db_result in db_results:
        item = ResultItem(
            atom_id=db_result.atom_id,
            requirement_text=db_result.requirement_text,
            classification=db_result.classification,
            confidence=db_result.confidence,
            module=db_result.module,
            country=db_result.country,
            wave=db_result.wave,
            rationale=db_result.rationale,
            reviewer_override=db_result.reviewer_override,
            d365_capability=db_result.d365_capability,
            d365_navigation=db_result.d365_navigation,
            config_steps=db_result.config_steps,
            gap_description=db_result.gap_description,
            configuration_steps=db_result.configuration_steps,
            dev_effort=db_result.dev_effort,
            gap_type=db_result.gap_type,
        )

        # Attach evidence if available
        if db_result.evidence:
            evidence_dict = db_result.evidence
            item.evidence = EvidenceItem(
                top_capability_score=evidence_dict.get("top_capability_score", 0.0),
                retrieval_confidence=evidence_dict.get("retrieval_confidence", "LOW"),
                prior_fitments=[
                    PriorFitmentItem(**pf)
                    for pf in evidence_dict.get("prior_fitments", [])
                ],
            )

        result_items.append(item)

    return PublicResultsResponse(
        batch_id=batch_id,
        product=batch.product,
        country=batch.country,
        wave=batch.wave,
        submitted_at=batch.created_at,
        reviewed_by=None,
        summary=BatchSummary(**batch.summary),
        requirements=result_items,
    )


# ---------------------------------------------------------------------------
# 9. Public batch listing (dashboard — no product prefix)
# ---------------------------------------------------------------------------


@public_router.get("/batches")
async def list_all_batches(
    request: Request,
    limit: int = 20,
    status: str | None = None,
    page: int = 1,
) -> BatchHistoryResponse:
    pg = _get_pg(request)

    # Get total count for pagination (DB-level COUNT)
    total = await pg.count_batches(status=status)

    # Calculate offset and fetch this page only (DB-level OFFSET/LIMIT)
    offset = (page - 1) * limit
    db_batches = await pg.list_batches(
        status=status, offset=offset, limit=limit
    )

    # Convert DB records to API response items
    items: list[BatchHistoryItem] = []
    for db_batch in db_batches:
        items.append(
            BatchHistoryItem(
                batch_id=db_batch.batch_id,
                upload_filename=db_batch.upload_filename,
                product=db_batch.product_id,
                country=db_batch.country,
                wave=db_batch.wave,
                status=db_batch.status,
                summary=BatchSummary(**(
                    db_batch.summary
                    or {"total": 0, "fit": 0, "partial_fit": 0, "gap": 0}
                )),
                created_at=db_batch.created_at.isoformat(),
                completed_at=(
                    db_batch.completed_at.isoformat()
                    if db_batch.completed_at else None
                ),
            )
        )

    return BatchHistoryResponse(
        batches=items,
        total=total,
        page=page,
        limit=limit,
    )
