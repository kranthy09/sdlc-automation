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
    status: Literal["uploaded", "already_exists"] = "uploaded"


class RunRequest(BaseModel):
    upload_id: str
    config_overrides: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    batch_id: str
    upload_id: str
    status: Literal["queued"] = "queued"
    websocket_url: str


class PriorFitmentItem(BaseModel):
    wave: int
    country: str
    classification: str


class EvidenceItem(BaseModel):
    top_capability_score: float = 0.0
    retrieval_confidence: str = "LOW"
    prior_fitments: list[PriorFitmentItem] = Field(default_factory=list)


class CapabilityItem(BaseModel):
    name: str
    score: float
    navigation: str


class ReviewItemEvidence(BaseModel):
    capabilities: list[CapabilityItem] = Field(default_factory=list)
    prior_fitments: list[PriorFitmentItem] = Field(default_factory=list)
    anomaly_flags: list[str] = Field(default_factory=list)


class ModuleSummary(BaseModel):
    fit: int = 0
    partial_fit: int = 0
    gap: int = 0


class BatchSummary(BaseModel):
    total: int
    fit: int
    partial_fit: int
    gap: int
    by_module: dict[str, ModuleSummary] = Field(default_factory=dict)


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
    d365_capability: str = ""
    d365_navigation: str = ""
    evidence: EvidenceItem = Field(default_factory=EvidenceItem)


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
    evidence: ReviewItemEvidence = Field(default_factory=ReviewItemEvidence)


class AutoApprovedItem(BaseModel):
    atom_id: str
    requirement_text: str
    classification: str
    confidence: float
    module: str
    rationale: str
    d365_capability: str = ""
    d365_navigation: str = ""


class ReviewQueueResponse(BaseModel):
    batch_id: str
    status: str
    items: list[ReviewItem]
    auto_approved: list[AutoApprovedItem] = Field(default_factory=list)


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
    total: int
    page: int
    limit: int
