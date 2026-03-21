"""
API-level Pydantic models for DYNAFIT routes.

Kept separate from platform/schemas/ — these are the HTTP contract shapes,
not the internal pipeline schemas.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    upload_id: str
    filename: str
    size_bytes: int
    detected_format: str
    status: Literal["uploaded"] = "uploaded"


class RunRequest(BaseModel):
    upload_id: str
    config_overrides: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    batch_id: str
    upload_id: str
    status: Literal["queued"] = "queued"
    websocket_url: str


class BatchSummary(BaseModel):
    total: int
    fit: int
    partial_fit: int
    gap: int


class ResultItem(BaseModel):
    atom_id: str
    requirement_text: str
    classification: str
    confidence: float
    module: str
    country: str
    wave: int
    rationale: str
    reviewer_override: bool = False


class ResultsResponse(BaseModel):
    batch_id: str
    status: str
    total: int
    page: int
    limit: int
    results: list[ResultItem]
    summary: BatchSummary


class ReviewItem(BaseModel):
    atom_id: str
    requirement_text: str
    ai_classification: str
    ai_confidence: float
    ai_rationale: str
    review_reason: str


class ReviewQueueResponse(BaseModel):
    batch_id: str
    status: str
    items: list[ReviewItem]


class ReviewDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "OVERRIDE", "FLAG"]
    override_classification: str | None = None
    reason: str = ""
    reviewer: str


class ReviewDecisionResponse(BaseModel):
    atom_id: str
    final_classification: str
    reviewer_override: bool
    remaining_reviews: int


class BatchRecord(BaseModel):
    batch_id: str
    upload_filename: str
    country: str
    wave: int
    status: str
    summary: BatchSummary
    created_at: str
    completed_at: str | None = None


class BatchHistoryResponse(BaseModel):
    batches: list[BatchRecord]
