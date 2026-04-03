"""
API-level Pydantic models for REQFIT routes.

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


class CandidateCapabilityItem(BaseModel):
    name: str
    score: float
    navigation: str


class EvidenceItem(BaseModel):
    top_capability_score: float = 0.0
    retrieval_confidence: str = "LOW"
    prior_fitments: list[PriorFitmentItem] = Field(default_factory=list)
    candidates: list[CandidateCapabilityItem] = Field(default_factory=list)
    route: str = ""
    anomaly_flags: list[str] = Field(default_factory=list)
    signal_breakdown: dict[str, float] = Field(default_factory=dict)


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


class BatchView(BaseModel):
    """Typed view of a batch with durable + transient state.

    Durable fields (from PostgreSQL):
      batch_id, upload_id, upload_filename, product, country, wave, status,
      summary, report_path, created_at, completed_at

    Transient fields (from Redis, optional):
      phases, classifications, journey, review_items, auto_approved
    """

    # Durable state (PostgreSQL)
    batch_id: str
    upload_id: str
    upload_filename: str
    product: str = ""
    country: str = ""
    wave: int = 1
    status: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    report_path: str | None = None
    created_at: str = ""
    completed_at: str | None = None

    # Transient state (Redis)
    phases: dict[str, Any] = Field(default_factory=dict)
    classifications: list[dict[str, Any]] = Field(default_factory=list)
    journey: list[dict[str, Any]] = Field(default_factory=list)
    review_items: list[dict[str, Any]] = Field(default_factory=list)
    auto_approved: list[dict[str, Any]] = Field(default_factory=list)


class ResultItem(BaseModel):
    atom_id: str
    requirement_text: str
    classification: str
    confidence: float
    module: str
    country: str
    wave: int = 1
    rationale: str
    reviewer_override: bool = False
    d365_capability: str = ""
    d365_navigation: str = ""
    evidence: EvidenceItem = Field(default_factory=EvidenceItem)
    config_steps: str | None = None
    gap_description: str | None = None
    configuration_steps: list[str] | None = None
    dev_effort: str | None = None
    gap_type: str | None = None
    caveats: str | None = None
    route_used: str = ""
    journey: AtomJourney | None = None


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
    module: str = ""
    evidence: ReviewItemEvidence = Field(default_factory=ReviewItemEvidence)
    config_steps: str | None = None
    gap_description: str | None = None
    configuration_steps: list[str] | None = None
    dev_effort: str | None = None
    gap_type: str | None = None
    reviewed: bool = False


class ReviewItemBasic(BaseModel):
    """Lightweight review item from PostgreSQL — decision metadata only.

    Contains only durable fields persisted to PostgreSQL. Rich context
    (requirement_text, ai_confidence, ai_rationale, evidence, etc.) is
    stored in Redis and may be stale or unavailable after process restart.
    """

    atom_id: str
    ai_classification: str
    ai_confidence: float | None = None
    decision: str | None = None
    override_classification: str | None = None
    reviewer: str | None = None
    reviewed: bool = False


class AutoApprovedItem(BaseModel):
    atom_id: str
    requirement_text: str
    classification: str
    confidence: float
    module: str
    rationale: str
    d365_capability: str = ""
    d365_navigation: str = ""
    config_steps: str | None = None
    configuration_steps: list[str] | None = None
    gap_description: str | None = None
    gap_type: str | None = None
    dev_effort: str | None = None
    evidence: ReviewItemEvidence = Field(default_factory=ReviewItemEvidence)


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


class BatchHistoryItem(BaseModel):
    batch_id: str
    upload_filename: str
    product: str = ""
    country: str
    wave: int
    status: str
    summary: BatchSummary
    created_at: str
    completed_at: str | None = None
    report_path: str | None = None


class BatchHistoryResponse(BaseModel):
    batches: list[BatchHistoryItem]
    total: int
    page: int
    limit: int


class BatchInput(BaseModel):
    """Worker write-back for batch completion metadata."""

    status: str
    completed_at: str | None = None
    report_path: str | None = None
    summary: dict[str, Any] | None = None


class UploadMetadata(BaseModel):
    """Upload file metadata passed to Celery worker."""

    upload_id: str
    filename: str
    path: str
    product: str
    country: str
    wave: int
    size_bytes: int
    detected_format: str
    content_hash: str


class DocumentMetadata(BaseModel):
    """Metadata embedded in Qdrant payload for docs."""

    id: str
    module: str
    feature: str
    url: str | None = None


class DocumentItem(BaseModel):
    """Single document from knowledge base."""

    id: str
    module: str
    feature: str
    title: str
    text: str
    url: str | None = None
    score: float | None = None


class KnowledgeBaseListResponse(BaseModel):
    """Response for knowledge base documents query."""

    product: str
    documents: list[DocumentItem]
    total_count: int
    module_counts: dict[str, int] = Field(default_factory=dict)


class PipelineConfig(BaseModel):
    """Full pipeline configuration for Celery task execution."""

    config_overrides: dict[str, Any] = Field(default_factory=dict)
    upload_meta: UploadMetadata
    resume: bool = False
    overrides: dict[str, Any] = Field(default_factory=dict)


class PublicResultsResponse(BaseModel):
    batch_id: str
    product: str
    country: str
    wave: int
    submitted_at: str
    reviewed_by: str | None = None
    summary: BatchSummary
    requirements: list[ResultItem]


# ---------------------------------------------------------------------------
# Journey (requirement traceability across pipeline phases)
# ---------------------------------------------------------------------------


class JourneyIngest(BaseModel):
    atom_id: str
    requirement_text: str
    module: str
    country: str = ""
    intent: str
    priority: str
    entity_hints: list[str] = Field(default_factory=list)
    specificity_score: float = 0.0
    completeness_score: float = 0.0
    content_type: str = "text"
    source_refs: list[str] = Field(default_factory=list)


class JourneyCapability(BaseModel):
    name: str
    score: float
    navigation: str


class JourneyDocRef(BaseModel):
    title: str
    score: float


class JourneyRetrieve(BaseModel):
    capabilities: list[JourneyCapability] = Field(default_factory=list)
    ms_learn_refs: list[JourneyDocRef] = Field(default_factory=list)
    prior_fitments: list[PriorFitmentItem] = Field(default_factory=list)
    retrieval_confidence: str = "LOW"


class JourneyMatch(BaseModel):
    signal_breakdown: dict[str, float] = Field(default_factory=dict)
    composite_score: float = 0.0
    route: str = ""
    anomaly_flags: list[str] = Field(default_factory=list)


class JourneyClassify(BaseModel):
    classification: str
    confidence: float
    rationale: str
    route_used: str
    llm_calls_used: int = 1
    d365_capability: str = ""
    d365_navigation: str = ""


class JourneyOutput(BaseModel):
    classification: str
    confidence: float
    config_steps: str | None = None
    configuration_steps: list[str] | None = None
    gap_description: str | None = None
    gap_type: str | None = None
    dev_effort: str | None = None
    reviewer_override: bool = False


class AtomJourney(BaseModel):
    atom_id: str
    ingest: JourneyIngest
    retrieve: JourneyRetrieve
    match: JourneyMatch
    classify: JourneyClassify
    output: JourneyOutput


class JourneyResponse(BaseModel):
    batch_id: str
    atoms: list[AtomJourney]


class PhaseProgressItem(BaseModel):
    phase: int
    phase_name: str
    status: Literal["pending", "active", "complete", "error"] = "pending"
    current_step: str | None = None
    progress_pct: int = 0
    atoms_produced: int = 0
    atoms_validated: int = 0
    atoms_flagged: int = 0
    latency_ms: float | None = None


class ProgressClassificationItem(BaseModel):
    atom_id: str
    classification: str
    confidence: float
    requirement_text: str = ""
    module: str = ""
    rationale: str = ""
    d365_capability: str = ""
    d365_navigation: str = ""
    journey: dict[str, Any] | None = None


class ProgressResponse(BaseModel):
    batch_id: str
    status: str
    phases: list[PhaseProgressItem]
    classifications: list[ProgressClassificationItem] = Field(
        default_factory=list,
    )


# ---------------------------------------------------------------------------
# Phase gate responses
# ---------------------------------------------------------------------------


class ProceedResponse(BaseModel):
    """Response when analyst approves proceeding from a phase gate."""

    batch_id: str
    status: Literal["proceeding"] = "proceeding"
    next_phase: int


class GateAtomsResponse(BaseModel):
    """Response containing summary data for a phase gate."""

    batch_id: str
    gate: int
    rows: list[dict[str, Any]]
