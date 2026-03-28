# Key Schemas — Data Structures

Reference for common data structures. Detailed defs in `platform/schemas/`.

---

## Input / Output

**RawUpload** — User provides file
```
filename: str
file_bytes: bytes
upload_id: str
```
Location: `platform/schemas/upload.py`

**DocumentFormat** — Detected format (PDF | DOCX | TXT)
```
format: DocumentFormat enum
confidence: float
encoding: str
```
Location: `platform/schemas/documents.py`

---

## Requirements

**RequirementAtom** — Single requirement from document
```
id: str (unique within batch)
text: str
req_id: str | None (from document)
module: str | None (D365 area)
country: str | None (legal entity)
priority: str | None (Must/Should/Could)
source_file: str (which document)
source_page: int | None
```
Location: `platform/schemas/requirements.py`

**AtomizedBatch** — Output of Phase 1
```
batch_id: str
atoms: list[RequirementAtom]
document_count: int
parsed_at: datetime
```
Location: `platform/schemas/batches.py`

---

## Retrieval

**RetrievalResult** — RAG output (Phase 2)
```
atom_id: str
similar_atoms: list[RequirementAtom]  # From KB
scores: list[float]  # Dense + BM25 + cross-encoder
rank: int
```
Location: `platform/schemas/retrieval.py`

---

## Classification

**ClassificationResult** — LLM output (Phase 4)
```
atom_id: str
classification: "FIT" | "GAP" | "REVIEW_REQUIRED"
confidence: float (0.0-1.0)
rationale: str
matched_features: list[str] | None  # If FIT
```
Location: `platform/schemas/fitment.py`

**ValidatedFitmentBatch** — Final output (Phase 5)
```
batch_id: str
results: list[ClassificationResult]
flagged_for_review: list[ClassificationResult]
human_overrides: dict[str, str]  # atom_id -> new classification
completed_at: datetime
```
Location: `platform/schemas/batches.py`

---

## Guardrails

**FileValidationResult** — File check (G1-lite)
```
passed: bool
filename: str
file_size: int
file_hash: str (SHA-256)
flags: list[str]
```
Location: `platform/schemas/guardrails.py`

**InjectionScanResult** — Prompt injection check (G3-lite)
```
severity: "PASS" | "FLAG_FOR_REVIEW" | "BLOCK"
score: float (0.0-1.0)
matched_patterns: list[str]
```
Location: `platform/schemas/guardrails.py`

**GuardrailResult** — Generic guardrail output
```
passed: bool
severity: "PASS" | "FLAG_FOR_REVIEW" | "BLOCK"
flags: list[str]
"""
Location: `platform/schemas/guardrails.py`

---

## Events

**PhaseStartEvent** — Published at phase start
```
batch_id: str
phase: int (1-5)
phase_name: str
timestamp: datetime
```
Location: `platform/schemas/events.py`

**PhaseCompleteEvent** — Published at phase end
```
batch_id: str
phase: int
status: "success" | "failed"
result_count: int
timestamp: datetime
```
Location: `platform/schemas/events.py`

---

## Config

**Settings** — Environment-driven config
```
LLM_MODEL: str  # "claude-3-5-sonnet-20241022"
LLM_MAX_RETRIES: int  # 3
POSTGRES_DSN: str
REDIS_URL: str
QDRANT_URL: str
QDRANT_COLLECTION: str  # "requirements"
MAX_FILE_SIZE_MB: int  # 50
CLASSIFICATION_CONFIDENCE_THRESHOLD: float  # 0.75
```
Location: `platform/config/settings.py`

---

## Full Definitions

For complete type annotations, see:

| Schema | Location |
|--------|----------|
| Batch objects | `platform/schemas/batches.py` |
| Requirements | `platform/schemas/requirements.py` |
| Classification | `platform/schemas/fitment.py` |
| Retrieval | `platform/schemas/retrieval.py` |
| Guardrails | `platform/schemas/guardrails.py` |
| Events | `platform/schemas/events.py` |
| Config | `platform/config/settings.py` |

Run `python -c "from platform.schemas import *; print(RawUpload.__doc__)"` to inspect.
