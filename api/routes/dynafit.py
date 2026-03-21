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

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.models import (
    BatchHistoryResponse,
    BatchRecord,
    BatchSummary,
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

log = structlog.get_logger(__name__)

router = APIRouter(tags=["dynafit"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/dynafit_uploads"))

# In-memory state — replaced by PostgreSQL in Session B
_uploads: dict[str, dict[str, Any]] = {}
_batches: dict[str, dict[str, Any]] = {}


def _dispatch(batch_id: str, upload_id: str, config: dict[str, Any]) -> None:
    """Enqueue the pipeline task. Upload metadata is included so the Celery
    worker (separate process) can reconstruct RawUpload without shared memory."""
    try:
        from api.workers.tasks import run_dynafit_pipeline  # noqa: PLC0415

        run_dynafit_pipeline.delay(batch_id, upload_id, config)
    except ImportError:
        log.warning("celery_not_ready", batch_id=batch_id)


def _dispatch_resume(batch_id: str) -> None:
    """Enqueue a resume-only run for Phase 5 after HITL review completes."""
    try:
        from api.workers.tasks import run_dynafit_pipeline  # noqa: PLC0415

        run_dynafit_pipeline.delay(batch_id, "", {"_resume": True})
    except ImportError:
        log.warning("celery_not_ready_resume", batch_id=batch_id)


def _get_batch(batch_id: str) -> dict[str, Any]:
    batch = _batches.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"batch_id {batch_id!r} not found")
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
    dest_path = dest_dir / filename
    content = await file.read()
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
        raise HTTPException(status_code=404, detail=f"upload_id {body.upload_id!r} not found")

    up = _uploads[body.upload_id]
    batch_id = f"bat_{uuid.uuid4().hex[:8]}"
    _batches[batch_id] = {
        "batch_id": batch_id,
        "upload_id": body.upload_id,
        "upload_filename": up["filename"],
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
# 3. Batch history  (declared before /{batch_id}/... to avoid routing ambiguity)
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
    if country:
        batches = [b for b in batches if b["country"] == country]
    if wave is not None:
        batches = [b for b in batches if b["wave"] == wave]
    if status:
        batches = [b for b in batches if b["status"] == status]

    start = (page - 1) * limit
    return BatchHistoryResponse(
        batches=[
            BatchRecord(
                batch_id=b["batch_id"],
                upload_filename=b["upload_filename"],
                country=b["country"],
                wave=b["wave"],
                status=b["status"],
                summary=BatchSummary(**b["summary"]),
                created_at=b["created_at"],
                completed_at=b.get("completed_at"),
            )
            for b in batches[start : start + limit]
        ]
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
# 5. Review queue
# ---------------------------------------------------------------------------


@router.get("/d365_fo/dynafit/{batch_id}/review")
def get_review_queue(batch_id: str) -> ReviewQueueResponse:
    batch = _get_batch(batch_id)
    return ReviewQueueResponse(
        batch_id=batch_id,
        status=batch["status"],
        items=[ReviewItem(**i) for i in batch["review_items"]],
    )


# ---------------------------------------------------------------------------
# 6a. Complete review — resume pipeline after all HITL items resolved
# ---------------------------------------------------------------------------


@router.post("/d365_fo/dynafit/{batch_id}/review/complete", status_code=202)
def complete_review(batch_id: str) -> dict[str, str]:
    _get_batch(batch_id)  # 404 if unknown
    _dispatch_resume(batch_id)
    log.info("review_complete_dispatched", batch_id=batch_id)
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
        raise HTTPException(status_code=404, detail=f"atom_id {atom_id!r} not in review queue")
    if body.decision == "OVERRIDE" and not body.override_classification:
        raise HTTPException(status_code=422, detail="override_classification required for OVERRIDE")

    item["reviewed"] = True
    item["decision"] = body.decision
    item["reviewer"] = body.reviewer

    final = (
        body.override_classification if body.decision == "OVERRIDE" else item["ai_classification"]
    )
    remaining = sum(1 for i in items if not i.get("reviewed", False))

    log.info("review_submitted", batch_id=batch_id, atom_id=atom_id, decision=body.decision)
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
def download_report(batch_id: str) -> FileResponse:
    batch = _get_batch(batch_id)
    report_path = batch.get("report_path")
    if not report_path or not Path(report_path).exists():
        raise HTTPException(status_code=404, detail="Report not yet generated")
    return FileResponse(
        path=report_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"fitment_matrix_{batch_id}.xlsx",
    )
