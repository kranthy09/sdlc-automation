# REQFIT Dynafit — Data Schemas & Types

**Location:** `platform/schemas/fitment.py`, `modules/dynafit/schemas.py`

All Pydantic v2 with strict validation.

---

## Phase Input/Output Schemas

```python
class RawUpload(BaseModel):
    filename: str
    file_bytes: bytes
    upload_id: str
    product_id: str = "d365_fo"
    country: str | None = None
    wave: int | None = None

class RequirementAtom(BaseModel):
    atom_id: str  # REQ-001, R12-3, etc.
    text: str
    section_path: str | None
    requirement_id: str | None
    priority: Literal["Must", "Should", "Could", "Won't"] | None = None
    source_page: int | None = None

class PriorFitment(BaseModel):
    prior_requirement_id: str
    fitted_module: str
    fitted_classification: Literal["FIT", "GAP", "PARTIAL_FIT"]
    similarity_score: float
    reviewer_override: bool = False

class MatchResult(BaseModel):
    atom_id: str
    text: str
    matched_modules: list[dict]  # {module_name, capability, scores}
    top_composite_score: float
```

---

## Classification Result

```python
class ClassificationResult(BaseModel):
    atom_id: str
    text: str
    classification: Literal["FIT", "GAP", "PARTIAL_FIT", "REVIEW_REQUIRED"]
    confidence: float  # 0.0-1.0
    rationale: str
    matched_features: list[str]

    gap_type: str | None = None  # "Missing module", "Insufficient config"
    gap_description: str | None = None
    dev_effort: Literal["S", "M", "L"] | None = None
    configuration_steps: list[str] | None = None

    evidence: dict  # {ingest, retrieve, match, classify, output}
    caveats: list[str] = []  # ["G11: PII", "G3: Injection risk"]
    route_used: Literal["FAST_TRACK", "DEEP_REASON", "GAP_CONFIRM"]
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

---

## State & Batch Schemas

```python
class DynafitState(BaseModel):
    batch_id: str
    upload_id: str
    atoms: list[RequirementAtom]
    match_results: list[MatchResult]
    classification_results: list[ClassificationResult]

    pii_redaction_map: dict[str, str] = {}  # placeholder → original
    flagged_for_review: list[ClassificationResult] = []
    human_overrides: dict[str, str] = {}  # {atom_id: override_class}

    product_id: str
    country: str | None
    config: ProductConfig

    created_at: datetime
    completed_at: datetime | None = None

class ValidatedFitmentBatch(BaseModel):
    batch_id: str
    upload_id: str
    results: list[ClassificationResult]
    flagged_for_review: list[ClassificationResult] = []
    auto_approved: list[ClassificationResult] = []
    summary: BatchSummary
    report_path: str | None = None
    completed_at: datetime
    status: Literal["completed"]
```

---

## Summary Schemas

```python
class ModuleSummary(BaseModel):
    module_name: str
    total: int
    fit: int
    gap: int
    partial_fit: int
    fit_rate: float

class BatchSummary(BaseModel):
    total: int
    fit: int
    gap: int
    partial_fit: int
    review_required: int
    by_module: dict[str, ModuleSummary] = {}
    fit_rate: float
    confidence_mean: float
    confidence_std: float
    pii_entities_redacted: int = 0
    injection_risk_detected: int = 0
    high_confidence_gaps: int = 0
    low_score_fits: int = 0
```

---

## WebSocket Events

```python
class PhaseStartEvent(BaseModel):
    batch_id: str
    phase: int
    phase_name: str
    timestamp: datetime

class PhaseCompleteEvent(BaseModel):
    batch_id: str
    phase: int
    result_count: int
    latency_ms: int
    guardrails_triggered: list[str]
    timestamp: datetime

class ReviewRequiredEvent(BaseModel):
    batch_id: str
    flagged_count: int
    flag_reasons: dict[str, int]
    timestamp: datetime

class BatchCompleteEvent(BaseModel):
    batch_id: str
    summary: BatchSummary
    report_path: str
    timestamp: datetime

class ErrorEvent(BaseModel):
    batch_id: str
    phase: int
    error: str
    recoverable: bool
    timestamp: datetime
```

---

## ProductConfig

```python
class ProductConfig(BaseModel):
    product_id: str  # "d365_fo"
    llm_model: str  # "claude-sonnet-4-6"
    embedding_model: str  # "BAAI/bge-small-en-v1.5"
    rerank_model: str  # "ms-marco-MiniLM-L-6-v2"

    fit_confidence_threshold: float = 0.85
    review_confidence_threshold: float = 0.60
    retrieval_confidence_threshold: float = 0.60

    capability_kb_namespace: str  # Qdrant
    historical_fitments_table: str  # PostgreSQL
    country_rules_path: str
    fdd_template_path: str
    code_language: str  # "xpp", "abap", "apex"
```

---

## Evidence Trail (Traceability)

Each `ClassificationResult.evidence` dict contains phase-by-phase trace:

- **ingest:** source_page, section, source_type (prose|table|image), extraction_method
- **retrieve:** embedding_model, top_k matches, prior_fitments[], latency_ms
- **match:** search_method, matched_modules[], top_score, latency_ms
- **classify:** llm_model, prompt_template, retries_used, latency_ms
- **output:** final_classification, final_confidence, human_reviewer, review_timestamp

**Purpose:** Audit trail + debugging + compliance traceability.
