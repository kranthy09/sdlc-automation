# platform/ — Layer 1 + Layer 2

## Current State

**Layer 1 (schemas) — COMPLETE**
```
platform/schemas/base.py        PlatformModel base
platform/schemas/product.py     ProductConfig — the multi-product key
platform/schemas/requirement.py RawUpload, RequirementAtom, ValidatedAtom, FlaggedAtom
platform/schemas/retrieval.py   RetrievalQuery, AssembledContext, RankedCapability, PriorFitment
platform/schemas/fitment.py     MatchResult, ClassificationResult, ValidatedFitmentBatch
platform/schemas/events.py      WebSocket message types
platform/schemas/errors.py      UnsupportedFormatError, ParseError, RetrievalError
```

**Layer 2 (utilities) — COMPLETE (13/13)**
- [x] `platform/config/settings.py`
- [x] `platform/observability/logger.py`
- [x] `platform/observability/metrics.py`
- [x] `platform/llm/client.py`
- [x] `platform/retrieval/embedder.py`
- [x] `platform/retrieval/vector_store.py`
- [x] `platform/retrieval/bm25.py`
- [x] `platform/retrieval/reranker.py`
- [x] `platform/parsers/format_detector.py` — detects PDF|DOCX|TXT only (no XLSX/ZIP)
- [x] `platform/parsers/docling_parser.py`
- [x] `platform/storage/postgres.py`
- [x] `platform/storage/redis_pub.py`
- [x] `platform/testing/factories.py`

**Layer 2 Extension — Guardrail Utilities (Session A, build before Layer 3 phase nodes)**
- [ ] `platform/schemas/guardrails.py` + `platform/guardrails/file_validator.py` → tests/unit/test_file_validator.py
- [ ] `platform/guardrails/injection_scanner.py` → tests/unit/test_injection_scanner.py

See `docs/specs/guardrails.md` for full design. These are reusable across all future products.

## Platform Rules

- **No imports from `agents/`, `modules/`, or `api/`** — ever
- `platform/observability/logger.py` is the **first import** in every other platform component
- `platform/observability/metrics.py` emits at **every external call** (LLM, Qdrant, Postgres, Redis)
- `platform/retrieval/vector_store.py` exposes an **interface**, not Qdrant types — swappable
- `platform/testing/factories.py` provides **all mocks** — module tests never instantiate real infra
- LLM retry logic lives **only** in `platform/llm/client.py` — never elsewhere

## Test Placement

- Unit tests (no Docker): `tests/unit/test_{component}.py`
- Integration tests (real Docker services): `tests/integration/test_{component}.py`
- Write the test before the implementation (RED → GREEN)
