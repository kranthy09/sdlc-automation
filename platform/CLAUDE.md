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

**Layer 2 (utilities) — build one component at a time in this order:**
- [ ] `platform/config/settings.py` ← start here
- [ ] `platform/observability/logger.py`
- [ ] `platform/observability/metrics.py`
- [ ] `platform/llm/client.py`
- [ ] `platform/retrieval/embedder.py`
- [ ] `platform/retrieval/vector_store.py`
- [ ] `platform/retrieval/bm25.py`
- [ ] `platform/retrieval/reranker.py`
- [ ] `platform/parsers/format_detector.py` — detects PDF|DOCX|TXT only (no XLSX/ZIP)
- [ ] `platform/parsers/docling_parser.py`
- [ ] `platform/storage/postgres.py`
- [ ] `platform/storage/redis_pub.py`
- [ ] `platform/testing/factories.py`

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
