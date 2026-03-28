# API Schemas — Request/Response Data Types

**Location:** `api/models.py`, `platform/schemas/fitment.py`

All schemas use Pydantic v2 with strict validation.

---

## Upload Schemas

```python
class UploadRequest(BaseModel):
    file: UploadFile  # multipart
    product: str = "d365_fo"
    country: str | None = None
    wave: int | None = None

class UploadResponse(BaseModel):
    upload_id: str  # Format: upl_{uuid[:8]}
    filename: str
    size_bytes: int
    detected_format: Literal["PDF", "DOCX", "TXT"]
    status: Literal["uploaded"]
    created_at: datetime
```

---

## Batch & Run Schemas

```python
class RunRequest(BaseModel):
    upload_id: str
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    # Can override: fit_confidence_threshold, review_confidence_threshold, etc.

class RunResponse(BaseModel):
    batch_id: str  # Format: bat_{uuid[:8]}
    upload_id: str
    status: Literal["queued"]
    websocket_url: str
    created_at: datetime

class BatchResponse(BaseModel):
    batch_id: str
    upload_id: str
    upload_filename: str
    status: Literal["queued", "processing", "awaiting_review", "completed", "failed"]
    phase: int | None  # 1-5, null if not started
    phase_name: str | None  # "Ingestion", "RAG", etc., null if not started
    result_count: int
    flagged_count: int
    created_at: datetime
    completed_at: datetime | None = None
    summary: BatchSummary | None = None
```

---

## Requirement & Result Schemas

```python
class RequirementAtom(BaseModel):
    atom_id: str  # REQ-001, REQ-002, etc.
    text: str
    section_path: str | None  # Where in doc (e.g., "2.1.3 Sales Order")
    priority: Literal["Must", "Should", "Could", "Won't"] | None
    requirement_id: str | None  # If linked to ID in doc

class ClassificationResult(BaseModel):
    atom_id: str
    text: str
    classification: Literal["FIT", "GAP", "PARTIAL_FIT", "REVIEW_REQUIRED"]
    confidence: float  # 0.0-1.0
    rationale: str  # LLM explanation
    matched_features: list[str]  # D365 capabilities matched
    evidence: EvidenceData
    caveats: list[str]  # Flags added by guardrails
    route_used: Literal["FAST_TRACK", "DEEP_REASON", "GAP_CONFIRM"]

class EvidenceData(BaseModel):
    ingest: dict  # Extracted metadata from document
    retrieve: dict  # Top K similar past requirements
    match: dict  # Module/feature matching scores
    classify: dict  # LLM decision context
    output: dict  # Final classification reasoning

class BatchResultsResponse(BaseModel):
    batch_id: str
    results: list[ClassificationResult]
    summary: BatchSummary
    fit_count: int
    gap_count: int
    partial_fit_count: int
    review_count: int
```

---

## Summary Schemas

```python
class ModuleSummary(BaseModel):
    module_name: str  # e.g., "Sales Order Management"
    total: int
    fit: int
    gap: int
    partial_fit: int
    fit_rate: float  # fit / total

class BatchSummary(BaseModel):
    total: int
    fit: int
    gap: int
    partial_fit: int
    by_module: dict[str, ModuleSummary] = Field(default_factory=dict)
    fit_rate: float  # Computed: fit / total
    confidence_mean: float  # Average FIT confidence
    confidence_std: float  # Std dev of FIT confidence
```

---

## Review/HITL Schemas

```python
class FlaggedItem(BaseModel):
    atom_id: str
    text: str
    ai_classification: Literal["FIT", "GAP", "PARTIAL_FIT"]
    confidence: float
    flag_reason: Literal[
        "high_confidence_gap",  # Score > 0.85 but classified GAP
        "low_score_fit",        # Score < 0.60 but classified FIT
        "llm_schema_retry_exhausted",  # Max retries failed
        "response_pii_leak",    # G11 detected PII in response
    ]
    rationale: str

class ReviewQueueResponse(BaseModel):
    batch_id: str
    flagged: list[FlaggedItem]
    total_flagged: int
    message: str  # "Awaiting human review"

class ReviewOverride(BaseModel):
    decision: Literal["APPROVE", "OVERRIDE"]
    override_classification: Literal["FIT", "GAP", "PARTIAL_FIT"] | None = None
    reviewer: str  # Email or user ID
    rationale: str | None = None

class ReviewAckResponse(BaseModel):
    atom_id: str
    decision_accepted: bool
    timestamp: datetime
```

---

## Error Schemas

```python
class ErrorResponse(BaseModel):
    detail: str
    status: int
    error_code: str  # BATCH_NOT_FOUND, INVALID_STATUS, etc.
    timestamp: datetime
    request_id: str | None = None  # For tracing

class ValidationError(BaseModel):
    detail: str
    errors: list[dict]  # Pydantic field errors
    status: 422
```

---

## ProductConfig (Read from Knowledge Base)

```python
class ProductConfig(BaseModel):
    product_id: str  # "d365_fo"
    llm_model: str  # "claude-sonnet-4-6"
    embedding_model: str  # "BAAI/bge-small-en-v1.5"
    fit_confidence_threshold: float  # Default 0.85
    review_confidence_threshold: float  # Default 0.60
    capability_kb_namespace: str  # Qdrant collection
    historical_fitments_table: str  # PostgreSQL table
    country_rules_path: str  # Path to country-specific rules
    fdd_template_path: str  # Path to FDD templates
    code_language: str  # "xpp", "abap", "apex"
```

---

## Field Constraints & Validation

| Field | Type | Constraint | Example |
|-------|------|-----------|---------|
| `batch_id` | str | `^bat_[a-z0-9]{8}$` | `bat_a1b2c3d4` |
| `upload_id` | str | `^upl_[a-z0-9]{8}$` | `upl_x9y8z7w6` |
| `atom_id` | str | No constraint | `REQ-001`, `R12-3`, `A001` |
| `classification` | enum | FIT\|GAP\|PARTIAL_FIT\|REVIEW_REQUIRED | - |
| `confidence` | float | [0.0, 1.0], 2 decimals | 0.85, 0.92, 0.33 |
| `phase` | int | [1, 5] | - |
| `filename` | str | Max 255 chars, no `/\` | `requirements.pdf` |
| `size_bytes` | int | Max 50 MB (52,428,800) | - |
