"""
DYNAFIT API routes — thin dispatchers only.

Rule: zero business logic here. Routes validate input, persist minimal
metadata, dispatch to Celery, and return. All computation lives in
modules/dynafit/ and is invoked by api/workers/tasks.py (Session B).

State store:
  _uploads / _batches are in-memory dicts for MVP.
  Session B replaces these with PostgreSQL queries.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from api.models import (
    AtomJourney,
    AutoApprovedItem,
    BatchHistoryResponse,
    BatchRecord,
    BatchSummary,
    JourneyResponse,
    PhaseProgressItem,
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
from platform.parsers.format_detector import detect_format
from platform.schemas.errors import UnsupportedFormatError
from platform.storage.redis_pub import RedisPubSub

log = structlog.get_logger(__name__)

router = APIRouter(tags=["dynafit"])
public_router = APIRouter(tags=["public"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/dynafit_uploads"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# In-memory state — replaced by PostgreSQL in Session B
_uploads: dict[str, dict[str, Any]] = {}
_batches: dict[str, dict[str, Any]] = {}


def _dispatch(batch_id: str, upload_id: str, config: dict[str, Any]) -> None:
    """Enqueue the pipeline task. Upload metadata is included so the Celery
    worker (separate process) can reconstruct RawUpload without shared
    memory."""
    try:
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

        run_dynafit_pipeline.delay(batch_id, "", {"_resume": True, "_overrides": overrides})
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
        is_override = item.get("decision") == "OVERRIDE" and item.get("override_classification")
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


def _sync_from_redis(batch: dict[str, Any], batch_id: str) -> None:
    """Merge Celery-written state from Redis into the in-memory batch.

    The Celery worker (separate OS process) writes results, review_items,
    status, summary, report_path, and completed_at to a Redis hash keyed
    by batch:{batch_id}.  This function merges those fields so REST routes
    return real data without shared memory.

    Scalar fields (status, summary, report_path, completed_at) are always
    refreshed from Redis — they are authoritative from the worker.
    List fields (results, review_items) are only loaded when empty in
    memory, preserving any submit_review() mutations made in-process.
    """
    data = RedisPubSub.read_batch_state_sync(REDIS_URL, batch_id)
    if not data:
        return

    # Always refresh authoritative scalar fields from the worker
    if "status" in data:
        batch["status"] = data["status"]
    if "report_path" in data and data["report_path"]:
        batch["report_path"] = data["report_path"]
    if "completed_at" in data and data["completed_at"]:
        batch["completed_at"] = data["completed_at"]
    if "summary" in data:
        try:
            batch["summary"] = json.loads(data["summary"])
        except json.JSONDecodeError:
            pass

    # Only load lists when empty — preserves submit_review() mutations
    if "review_items" in data and not batch.get("review_items"):
        try:
            batch["review_items"] = json.loads(data["review_items"])
        except json.JSONDecodeError:
            pass
    if "results" in data and not batch.get("results"):
        try:
            batch["results"] = json.loads(data["results"])
        except json.JSONDecodeError:
            pass
    if "auto_approved" in data and not batch.get("auto_approved"):
        try:
            batch["auto_approved"] = json.loads(data["auto_approved"])
        except json.JSONDecodeError:
            pass
    if "journey" in data and not batch.get("journey"):
        try:
            batch["journey"] = json.loads(data["journey"])
        except json.JSONDecodeError:
            pass


def _get_batch(batch_id: str) -> dict[str, Any]:
    batch = _batches.get(batch_id)
    if batch is None:
        raise HTTPException(
            status_code=404,
            detail=f"batch_id {batch_id!r} not found",
        )
    _sync_from_redis(batch, batch_id)
    return batch


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# 1. Upload
# ---------------------------------------------------------------------------


@router.post("/upload", status_code=201)
async def upload_file(
    file: UploadFile,
    product: str = Form(...),
    country: str = Form(...),
    wave: int = Form(...),
) -> UploadResponse:
    upload_id = f"upl_{uuid.uuid4().hex[:8]}"
    dest_dir = UPLOAD_DIR / upload_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = file.filename or "upload"
    content = await file.read()
    content_hash = hashlib.sha256(content).hexdigest()

    # Return existing upload if identical content was already uploaded
    for existing in _uploads.values():
        if existing.get("content_hash") == content_hash:
            log.info(
                "upload_duplicate_detected",
                existing_id=existing["upload_id"],
            )
            return UploadResponse(
                upload_id=existing["upload_id"],
                filename=existing["filename"],
                size_bytes=existing["size_bytes"],
                detected_format=existing["detected_format"].upper(),
                status="already_exists",
            )

    dest_path = dest_dir / filename
    dest_path.write_bytes(content)

    try:
        result = detect_format(dest_path)
    except UnsupportedFormatError as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _uploads[upload_id] = {
        "upload_id": upload_id,
        "filename": filename,
        "size_bytes": len(content),
        "detected_format": result.format,
        "path": str(dest_path),
        "product": product,
        "country": country,
        "wave": wave,
        "content_hash": content_hash,
    }
    log.info("upload_complete", upload_id=upload_id, fmt=result.format)
    return UploadResponse(
        upload_id=upload_id,
        filename=filename,
        size_bytes=len(content),
        detected_format=result.format.upper(),
    )


# ---------------------------------------------------------------------------
# 2. Start pipeline
# ---------------------------------------------------------------------------


@router.post("/d365_fo/dynafit/run", status_code=202)
def run_pipeline(body: RunRequest) -> RunResponse:
    if body.upload_id not in _uploads:
        raise HTTPException(
            status_code=404,
            detail=f"upload_id {body.upload_id!r} not found",
        )

    up = _uploads[body.upload_id]
    batch_id = f"bat_{uuid.uuid4().hex[:8]}"
    _batches[batch_id] = {
        "batch_id": batch_id,
        "upload_id": body.upload_id,
        "upload_filename": up["filename"],
        "product": up["product"],
        "country": up["country"],
        "wave": up["wave"],
        "status": "queued",
        "results": [],
        "review_items": [],
        "summary": {"total": 0, "fit": 0, "partial_fit": 0, "gap": 0},
        "report_path": None,
        "created_at": _now(),
        "completed_at": None,
    }
    # Pass upload metadata so the Celery worker can read the file
    full_config = {**body.config_overrides, "_upload_meta": dict(up)}
    _dispatch(batch_id, body.upload_id, full_config)
    log.info("pipeline_queued", batch_id=batch_id, upload_id=body.upload_id)
    return RunResponse(
        batch_id=batch_id,
        upload_id=body.upload_id,
        websocket_url=f"/api/v1/ws/progress/{batch_id}",
    )


# ---------------------------------------------------------------------------
# 3. Batch history (declared before /{batch_id}/... to avoid routing ambiguity)
# ---------------------------------------------------------------------------


@router.get("/d365_fo/dynafit/batches")
def list_batches(
    country: str | None = None,
    wave: int | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 10,
) -> BatchHistoryResponse:
    batches = list(_batches.values())
    # Sync status/summary from Redis so batch history reflects pipeline state
    for b in batches:
        _sync_from_redis(b, b["batch_id"])
    if country:
        batches = [b for b in batches if b["country"] == country]
    if wave is not None:
        batches = [b for b in batches if b["wave"] == wave]
    if status:
        batches = [b for b in batches if b["status"] == status]

    total = len(batches)
    start = (page - 1) * limit
    page_batches = batches[start : start + limit]
    return BatchHistoryResponse(
        batches=[
            BatchRecord(
                batch_id=b["batch_id"],
                upload_filename=b["upload_filename"],
                product=b.get("product", "d365_fo"),
                country=b["country"],
                wave=b["wave"],
                status=b["status"],
                summary=BatchSummary(**b["summary"]),
                created_at=b["created_at"],
                completed_at=b.get("completed_at"),
            )
            for b in page_batches
        ],
        total=total,
        page=page,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# 4. Results
# ---------------------------------------------------------------------------


@router.get("/d365_fo/dynafit/{batch_id}/results")
def get_results(
    batch_id: str,
    classification: str | None = None,
    module: str | None = None,
    page: int = 1,
    limit: int = 25,
) -> ResultsResponse:
    batch = _get_batch(batch_id)
    results: list[dict[str, Any]] = batch["results"]

    if classification:
        results = [r for r in results if r["classification"] == classification]
    if module:
        results = [r for r in results if r["module"] == module]

    start = (page - 1) * limit
    return ResultsResponse(
        batch_id=batch_id,
        status=batch["status"],
        total=len(results),
        page=page,
        limit=limit,
        results=[ResultItem(**r) for r in results[start : start + limit]],
        summary=BatchSummary(**batch["summary"]),
    )


# ---------------------------------------------------------------------------
# 4b. Journey (per-atom pipeline traceability)
# ---------------------------------------------------------------------------


@router.get("/d365_fo/dynafit/{batch_id}/journey")
def get_journey(
    batch_id: str,
    atom_id: str | None = None,
) -> JourneyResponse:
    batch = _get_batch(batch_id)
    if batch["status"] not in ("complete", "review_required"):
        raise HTTPException(
            status_code=409,
            detail="Journey data available only for completed batches",
        )
    journey: list[dict[str, Any]] = batch.get("journey", [])
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
def get_progress(batch_id: str) -> ProgressResponse:
    batch = _get_batch(batch_id)

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
        )
        for c in persisted_cls
    ]

    return ProgressResponse(
        batch_id=batch_id,
        status=batch["status"],
        phases=phases,
        classifications=classifications,
    )


# ---------------------------------------------------------------------------
# 5. Review queue
# ---------------------------------------------------------------------------


@router.get("/d365_fo/dynafit/{batch_id}/review")
def get_review_queue(batch_id: str) -> ReviewQueueResponse:
    batch = _get_batch(batch_id)
    return ReviewQueueResponse(
        batch_id=batch_id,
        status=batch["status"],
        items=[ReviewItem(**i) for i in batch["review_items"]],
        auto_approved=[AutoApprovedItem(**i) for i in batch.get("auto_approved", [])],
    )


# ---------------------------------------------------------------------------
# 6a. Complete review — resume pipeline after all HITL items resolved
# ---------------------------------------------------------------------------


@router.post("/d365_fo/dynafit/{batch_id}/review/complete", status_code=202)
def complete_review(batch_id: str) -> dict[str, str]:
    batch = _get_batch(batch_id)
    overrides = _build_overrides(batch["review_items"])
    _dispatch_resume(batch_id, overrides)
    log.info(
        "review_complete_dispatched",
        batch_id=batch_id,
        override_count=len(overrides),
    )
    return {"batch_id": batch_id, "status": "resumed"}


# ---------------------------------------------------------------------------
# 6b. Submit individual review decision
# ---------------------------------------------------------------------------


@router.post("/d365_fo/dynafit/{batch_id}/review/{atom_id}")
def submit_review(
    batch_id: str,
    atom_id: str,
    body: ReviewDecisionRequest,
) -> ReviewDecisionResponse:
    batch = _get_batch(batch_id)
    items: list[dict[str, Any]] = batch["review_items"]

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

    final = (
        body.override_classification if body.decision == "OVERRIDE" else item["ai_classification"]
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
# 7. Download report
# ---------------------------------------------------------------------------


@router.get("/d365_fo/dynafit/{batch_id}/report")
def download_report(
    batch_id: str,
    file: str | None = None,
) -> Response:
    """Download report CSV files.

    If ``file`` is omitted, returns a JSON manifest listing
    available CSVs. If ``file`` is specified, returns that
    individual CSV. No ZIP — stdlib csv only (project rule).
    """
    batch = _get_batch(batch_id)
    report_path = batch.get("report_path")
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
# 8. Public results (shareable read-only — no product prefix)
# ---------------------------------------------------------------------------


@public_router.get("/batches/{batch_id}/results")
def get_public_results(batch_id: str) -> PublicResultsResponse:
    batch = _get_batch(batch_id)
    results: list[dict[str, Any]] = batch["results"]
    return PublicResultsResponse(
        batch_id=batch_id,
        product=batch.get("product", "d365_fo"),
        country=batch["country"],
        wave=batch["wave"],
        submitted_at=batch["created_at"],
        reviewed_by=None,
        summary=BatchSummary(**batch["summary"]),
        requirements=[ResultItem(**r) for r in results],
    )


# ---------------------------------------------------------------------------
# 9. Public batch listing (dashboard — no product prefix)
# ---------------------------------------------------------------------------


@public_router.get("/batches")
def list_all_batches(
    limit: int = 20,
    status: str | None = None,
    page: int = 1,
) -> BatchHistoryResponse:
    batches = list(_batches.values())
    for b in batches:
        _sync_from_redis(b, b["batch_id"])
    if status:
        batches = [b for b in batches if b["status"] == status]
    total = len(batches)
    start = (page - 1) * limit
    page_batches = batches[start : start + limit]
    return BatchHistoryResponse(
        batches=[
            BatchRecord(
                batch_id=b["batch_id"],
                upload_filename=b["upload_filename"],
                product=b.get("product", "d365_fo"),
                country=b["country"],
                wave=b["wave"],
                status=b["status"],
                summary=BatchSummary(**b["summary"]),
                created_at=b["created_at"],
                completed_at=b.get("completed_at"),
            )
            for b in page_batches
        ],
        total=total,
        page=page,
        limit=limit,
    )
