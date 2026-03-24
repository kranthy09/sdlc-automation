# TDD Implementation Guide

## MVP Testing Philosophy

**Goal: fast to market, high confidence in core value, low maintenance cost.**

| Layer                | Test type      | What to test                                                                 |
| -------------------- | -------------- | ---------------------------------------------------------------------------- |
| Platform schemas     | Unit           | One valid case + invalid enum/range/required — trust Pydantic for the rest   |
| Platform utilities   | Unit           | Complex logic only: error-path branching, counter accuracy, retry behaviour  |
| Module nodes         | Unit (mocked)  | Non-trivial algorithms; skip simple pass-through nodes                       |
| End-to-end workflows | Integration    | The critical user journeys (upload -> classify -> report) with real services |
| LLM calls            | Golden fixture | Capture once, replay in CI — never live in CI                                |

**Do NOT write tests for:**

- Object construction ("can I instantiate X") — trust the import
- Simple defaults — they're in the schema definition, read it
- Every valid enum value — one valid + one invalid covers the contract
- Framework features: Pydantic `frozen`, `str_strip_whitespace`, SQLAlchemy sessions
- Duplicate-pattern validation (e.g. testing each missing required field separately)

**Write tests for:**

- Business rules: score ranges, wave >= 1, non-empty required text
- Error paths: exception re-raise, status="error" counter, transaction rollback
- Core journeys: requirement upload -> fitment CSV output (integration)

---

## TDD Cycle Pattern

For every component, follow this exact order:

```
1. Write the test (it fails — RED)
2. Write minimal code to pass (GREEN)
3. Refactor for production quality (REFACTOR)
4. Add edge case tests (RED again)
5. Handle edge cases (GREEN)
6. Move to next component
```

---

## Golden Fixtures for LLM Testing

Never call live LLMs in CI. Capture real responses once and replay them.

```python
# tests/fixtures/golden/phase4_classification.json
{
  "input": {
    "requirement_id": "REQ-AP-041",
    "requirement_text": "System must support three-way matching for purchase invoices",
    "top_capabilities": [
      {"id": "cap-ap-0001", "feature": "Three-way matching", "score": 0.94}
    ],
    "historical_precedent": {"wave_1_DE": "FIT", "confidence": 0.91}
  },
  "expected_output": {
    "classification": "FIT",
    "confidence_min": 0.85,
    "rationale_contains": ["three-way matching", "standard", "AP module"]
  }
}
```

```python
# tests/integration/test_phase4_golden.py
@pytest.mark.golden
class TestClassificationGolden:
    @pytest.fixture
    def golden_cases(self):
        return json.loads((GOLDEN_DIR / "phase4_classification.json").read_text())

    def test_classification_matches_golden(self, golden_cases, mock_llm):
        from modules.dynafit.nodes import classify_requirement
        result = classify_requirement(golden_cases["input"], llm=mock_llm)
        expected = golden_cases["expected_output"]
        assert result.classification == expected["classification"]
        assert result.confidence >= expected["confidence_min"]
        for term in expected["rationale_contains"]:
            assert term.lower() in result.rationale.lower()
```

---

## pytest Configuration

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests", "modules/dynafit/tests"]
markers = [
    "unit: fast, no external deps",
    "integration: needs Docker services",
    "golden: uses golden fixture files",
    "llm: needs live LLM (skip in CI)",
]
```

---

## Layer Build Order (completion tracking)

| Layer                        | Status | Key deliverables                                                                 |
| ---------------------------- | ------ | -------------------------------------------------------------------------------- |
| Layer 0 — Scaffold + CI      | DONE   | `make ci` passes on empty codebase, Docker services start, import validator runs |
| Layer 1 — Platform Schemas   | DONE   | All Pydantic contracts in `platform/schemas/`, `mypy --strict` passes            |
| Layer 2 — Platform Utilities | DONE   | 13 platform components + guardrail utilities, all tests pass                     |
| Layer 3 — REQFIT Module      | DONE   | All 5 phases, LangGraph graph wired, golden fixtures captured                    |
| Layer 4 — API + Workers + UI | DONE   | FastAPI routes, Celery worker, WebSocket, React UI (all pages + components)      |

### Platform Utility Build Order (Layer 2)

Observability before LLM client (so the client can log from birth):

```
platform/config/settings.py        -> tests/unit/test_settings.py
platform/observability/logger.py   -> tests/unit/test_logger.py
platform/observability/metrics.py  -> tests/unit/test_metrics.py
platform/llm/client.py             -> tests/unit/test_llm_client.py (mocked)
platform/retrieval/embedder.py     -> tests/unit/test_embedder.py (mocked model)
platform/retrieval/vector_store.py -> tests/integration/test_vector_store.py (real Qdrant)
platform/parsers/format_detector.py -> tests/unit/test_format_detector.py
platform/parsers/docling_parser.py -> tests/unit/test_docling_parser.py
platform/storage/postgres.py       -> tests/integration/test_postgres.py (real DB)
platform/storage/redis_pub.py      -> tests/integration/test_redis_pub.py (real Redis)
platform/testing/factories.py      -> no test (it IS the test helper)
```

### Knowledge Base Seeding

```bash
make seed-kb PRODUCT=d365_fo       # Load capabilities.jsonl into Qdrant
make seed-corpus PRODUCT=d365_fo   # Crawl MS Learn docs into Qdrant (~45 min first run)
```

### CI Workflow

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  quality:
    runs-on: ubuntu-latest
    services:
      postgres: { image: pgvector/pgvector:pg16, ports: ["5432:5432"] }
      redis: { image: redis:7-alpine, ports: ["6379:6379"] }
      qdrant: { image: qdrant/qdrant:latest, ports: ["6333:6333"] }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras
      - run: make lint
      - run: make validate-contracts
      - run: make test
```
