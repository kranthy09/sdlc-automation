# Rules — Read Before Writing Any Code

## Build Discipline

- **One component per session.** Confirm scope before writing code.
- **Only build explicitly requested** features. No anticipatory features.
- **Integration tests first.** Unit tests only for complex logic (algorithms, validation rules, error paths).

## Import Boundaries (CI-enforced)

```
platform/   cannot import from  agents/, modules/, api/
agents/     cannot import from  modules/, api/
modules/X/  cannot import from  modules/Y/
api/        can only import from modules/ graph entry points + platform/schemas/
```

Violations block merges. `make validate-contracts` runs on every PR.

## Code Standards

- **Python 3.12+** — type hints everywhere, `mypy --strict` must pass
- **Pydantic v2** at every layer boundary
- **Jinja2** for LLM prompts — never f-strings
- **structlog** for logging — JSON, correlation IDs
- **Prometheus metrics** at every external call (LLM, Qdrant, Postgres, Redis)
- **Retry logic in `platform/llm/client.py` only** — nodes call it
- **No direct infra calls from nodes** — never import `anthropic`, `qdrant_client`, or `sqlalchemy` in `modules/`
- **No free-text LLM parsing** — structured output via Pydantic

## CI Gates (all three must pass)

```bash
make lint               # ruff + mypy --strict
make test               # pytest --cov (unit + integration)
make validate-contracts # import boundary + manifest validation
```

---

## Architecture

### Layer Diagram

```
enterprise_ai/
+-- platform/        # Layer 1+2: shared infra (zero imports from above)
|   +-- schemas/     # Pydantic contracts (layer glue)
|   +-- config/      # Settings (no hardcoded values)
|   +-- observability/  # Logger, metrics
|   +-- llm/         # Claude wrapper
|   +-- retrieval/   # Embedder, Qdrant, reranker
|   +-- parsers/     # Document parsers
|   +-- storage/     # Postgres async, Redis pub/sub
|   +-- testing/     # Mock factories
+-- knowledge_bases/ # Product data: YAML + JSONL only
+-- agents/          # Reusable LangGraph nodes
+-- modules/         # Business modules (one per product)
+-- api/             # FastAPI + Celery dispatchers (zero logic)
+-- ui/              # React + Vite
+-- infra/           # Docker, Helm, scripts
```

### Dependency Law

```
api/ → modules/ → agents/ → platform/
```

**Never:** sideways (modules/X → modules/Y) or downward (platform/ → agents/)

### ProductConfig — Multi-Product Key

Every product-varying parameter in `ProductConfig`:

```python
class ProductConfig(PlatformModel):
    product_id: str
    llm_model: str                 # "claude-sonnet-4-6"
    embedding_model: str
    fit_confidence_threshold: float  # 0.85
    review_confidence_threshold: float  # 0.60
    country_rules_path: str
    fdd_template_path: str
    code_language: str
```

Nodes receive `ProductConfig` instance; never hardcode model names or thresholds.

### Production Failure Modes

| Failure | Resolution |
|---------|-----------|
| Node crash mid-batch | PostgresSaver checkpoints; LangGraph resumes |
| Qdrant timeout | 5s timeout, flag `retrieval_confidence=LOW` |
| LLM malformed output | XML → regex → Pydantic; 2 retries with error injection |
| Celery worker dies | `max_retries=2`; resume from checkpoint |
| WebSocket disconnect | Progress to Redis; client reconnects, fetches REST |

---

## CI Is Layer-Gated

CI pipeline grows with layers. Don't add service containers or ML deps until layer is built.

**Layer 0 (Current):**
- No service containers (Postgres, Redis, Qdrant)
- `uv sync --extra dev` (framework core + dev tooling)
- Runs: lint + validate-contracts + unit tests
- Completes in ~2 minutes

**Layer 2 Unlock:**
- Add Postgres, Redis, Qdrant containers
- `uv sync --extra dev --extra ml` in CI
- Add `pytest -m integration`

**Layer 3 Unlock:**
- Add `pytest -m golden` (golden fixture replay)

**Why:** torch/docling/spacy added 10–15 min build time for unused packages. ML extras only in CI when needed.

---

## Golden Fixtures

- Live LLM calls never in CI test suite
- Capture real responses → replay via `tests/fixtures/golden/`
- Mark with `@pytest.mark.golden` (live-LLM: `@pytest.mark.llm`, skipped in CI)

---

## Key Incidents → Rules

### One Component Per Session

Incident: Built all 15 Layer 2 utilities in one session (32 files, all discarded).

**Rule:** Confirm exact single component before coding. Build one per session, then stop.

### Excel & ZIP Not Supported

Incident: Added `excel_parser.py` without request; later removed as unsupported format.

**Rule:** PDF, DOCX, TXT input only. CSV output (stdlib, not Excel). `openpyxl` not a dependency.

### fastembed Not sentence-transformers

Incident: `sentence-transformers` pulls PyTorch (~500 MB); Docker build 409s.

**Rule:** Use `fastembed` (ONNX, ~50 MB, same models). Never add `sentence-transformers`.

### Never Hardcode product_id

Incident: `_get_embedder()` hardcoded `"d365_fo"` in two files; broke multi-product.

**Rule:** Accept `product_id` from state. Grep before merge for hardcoded product IDs.
