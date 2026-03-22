# Rules — Read Before Writing Any Code

## Build Discipline

- **One component per session.** Before writing code, confirm: "What exactly are we building today?"
- **Only build what is explicitly requested** for the current phase. No anticipatory features.
- **Confirm scope** before starting. If the request is vague, ask. Don't infer and over-build.
- **Layer order is strict.** Layer 2 utility before any Layer 3 node. No exceptions.
- **MVP Testing:** Integration tests for core business workflows first. Unit tests only for complex business logic (validation rules, algorithms, error-path branching). Never test constructors, simple defaults, Pydantic built-ins (frozen, whitespace stripping), or every enum value — one valid + one invalid case is enough.

## Import Boundaries (CI-enforced)

```
platform/   cannot import from  agents/, modules/, api/
agents/     cannot import from  modules/, api/
modules/X/  cannot import from  modules/Y/  (no cross-module imports, ever)
api/        can only import from modules/ graph entry points and platform/schemas/
```

Violations block merges. `make validate-contracts` runs on every PR.

## Code Standards

- **Python 3.12+**, type hints everywhere, `mypy --strict` must pass
- **Pydantic v2** at every layer boundary — input schema -> transform -> output schema
- **Jinja2** for all LLM prompt templates — never f-strings or string concatenation
- **structlog** for all logging — JSON, correlation IDs, bound via `contextvars`
- **Prometheus metrics** at every external call (LLM, Qdrant, Postgres, Redis) — not added later
- **Retry logic lives only in `platform/llm/client.py`** — nodes call it, never duplicate it
- **No direct infra calls from nodes** — never import `anthropic`, `qdrant_client`, or `sqlalchemy` in `modules/`
- **No free-text LLM parsing** — every LLM call uses structured output via Pydantic

### Ruff-enforced patterns (must pass before every push)

| Rule | What it catches | Correct pattern |
|------|----------------|-----------------|
| **I001** | Unsorted / unformatted import blocks | Run `make format` — never hand-sort |
| **UP024** | Legacy OS-error aliases | `OSError` not `IOError` / `EnvironmentError` |
| **UP035** | Deprecated `typing` imports | `from collections.abc import Generator` not `from typing import Generator` |
| **UP047** | Generic functions using `TypeVar` | PEP 695: `def fn[T: Base](...)` not `T = TypeVar(...)` for standalone functions |
| **F401** | Unused imports | Delete them; add `# noqa: F401` only for deliberate side-effect imports |
| **B** | Bugbear traps | No mutable defaults, no bare `except:`, no `assert` in production paths |

`make format` auto-fixes I001, UP024, UP035. UP047 on standalone functions requires a manual rewrite to PEP 695 syntax. Run `make lint` to confirm zero errors before pushing.

## What Nodes Must Do

```python
# WRONG — node owns infrastructure
from anthropic import Anthropic
client = Anthropic()

# RIGHT — node calls platform utility
from platform.llm.client import classify
result = classify(prompt, output_schema=MySchema, config=product_config)
```

## CI Gates (all three must pass on every PR)

```bash
make lint               # ruff + mypy --strict
make test               # pytest --cov (unit + integration)
make validate-contracts # import boundary + manifest schema validation
```

No merge bypasses these. Not for urgency. Not for hotfixes.

## Golden Fixtures

- Live LLM calls never appear in CI test suite
- Capture real LLM responses once -> replay in CI via `tests/fixtures/golden/`
- Mark tests with `@pytest.mark.golden`; mark live-LLM tests with `@pytest.mark.llm` (skipped in CI)

---

## Architecture

### Layer Diagram

```
enterprise_ai/
+-- platform/              # Layer 1+2: shared infra — zero imports from above
|   +-- schemas/           # Pydantic contracts (Layer 1) — the glue between all layers
|   +-- config/            # Pydantic Settings — no hardcoded values anywhere
|   +-- observability/     # structlog logger, Prometheus metrics
|   +-- llm/               # Claude wrapper: retry, structured output, cost tracking
|   +-- retrieval/         # Embedder, Qdrant hybrid search, BM25, cross-encoder reranker
|   +-- parsers/           # Format detector, document parsers
|   +-- storage/           # PostgreSQL async, Redis pub/sub
|   +-- testing/           # Mock factories shared by all module test suites
+-- knowledge_bases/       # Product data: YAML + JSONL only — never Python
|   +-- d365_fo/           # seed_data/, country_rules/, fdd_templates/
+-- agents/                # Reusable LangGraph nodes — no product knowledge
+-- modules/               # Business modules — one per product/workflow
|   +-- dynafit/           # 6-file pattern: manifest, graph, schemas, nodes, prompts/, tests/
+-- api/                   # FastAPI + Celery — dispatchers only, zero business logic
+-- ui/                    # React + Vite
+-- infra/                 # Docker Compose, Helm, scripts
```

### Dependency Law

```
api/ -> modules/ -> agents/ -> platform/
```

- Never sideways: `modules/dynafit/` cannot import from `modules/fdd/`
- Never downward: `platform/` cannot import from `agents/`, `modules/`, or `api/`

### Team Ownership

| Directory | Owner | Rule |
|-----------|-------|------|
| `platform/` | Core platform team | No business logic, no product knowledge |
| `knowledge_bases/` | Each product team | D365 team owns `d365_fo/`. YAML + JSONL only. |
| `agents/` | Core platform team | Reusable across ALL modules |
| `modules/dynafit/` | D365 team | Calls `platform/` only. Never modifies `platform/`. |
| `api/` | Core platform team | Routes dispatch only. Zero logic. |

### ProductConfig — The Multi-Product Key

Every parameter that varies by product lives in `ProductConfig`. Nodes receive a `ProductConfig` instance and never hardcode model names or thresholds.

```python
class ProductConfig(PlatformModel):
    product_id: str
    llm_model: str                      # "claude-sonnet-4-6"
    embedding_model: str                # "BAAI/bge-small-en-v1.5"
    capability_kb_namespace: str        # Qdrant collection name
    historical_fitments_table: str      # PostgreSQL table name
    fit_confidence_threshold: float     # 0.85
    review_confidence_threshold: float  # 0.60
    country_rules_path: str
    fdd_template_path: str
    code_language: str                  # "xpp", "abap", "apex"
```

### Production Failure Modes

| Failure | Resolution | Location |
|---------|-----------|----------|
| Node crash mid-batch | PostgresSaver checkpoints. LangGraph resumes from last node. | `modules/dynafit/graph.py` |
| Qdrant timeout | 5s timeout, proceed with available results, flag `retrieval_confidence=LOW` | `platform/retrieval/vector_store.py` |
| LLM malformed output | XML -> regex -> Pydantic. 2 retries with error injected. Failure = REVIEW_REQUIRED. | `platform/llm/client.py` |
| Celery worker dies | `max_retries=2`, LangGraph resumes from PostgreSQL checkpoint | `api/workers/tasks.py` |
| WebSocket disconnect | Progress publishes to Redis regardless. Client reconnects, fetches via REST. | `api/websocket/progress.py` |
| LLM cost overrun | Prometheus counter per call. Grafana alert at threshold. | `platform/observability/metrics.py` |

### New Product Onboarding (Zero Platform Changes)

```
Step 1 — Data only:
  knowledge_bases/sap_s4hana/product_config.yaml
  knowledge_bases/sap_s4hana/seed_data/capabilities.jsonl

Step 2 — New module, 6-file pattern:
  modules/fitment_sap/{manifest.yaml, graph.py, schemas.py, nodes.py, prompts/, tests/}

Step 3:
  make seed-kb PRODUCT=sap_s4hana
  make validate-contracts
```

If step 2 requires changes to `platform/`, `agents/`, or `api/` — the platform abstraction is wrong. Fix it first.

---

## Lessons Learned

Every entry here came from a real mistake. Rules are concrete, not general advice.

### Incident: Layer 2 built entirely in one session

Claude built all 15 Layer 2 platform utilities in a single session, including `excel_parser.py` which was not requested. The session ended with 32 new files — none committed, all discarded.

**Rules produced:**
- Confirm the exact single component before writing any code
- Build one component per session, then stop
- Only build what is explicitly requested — no anticipatory features

### Incident: Root CLAUDE.md grew to 524 lines

CLAUDE.md accumulated every specification. At 524 lines it filled the context with irrelevant information.

**Rules produced:**
- Root CLAUDE.md hard cap: 60 lines
- All detail belongs in `docs/specs/` — CLAUDE.md is a pointer, not a spec

### Decision: Excel and ZIP removed from supported formats

All real-world requirement documents arrive as PDF, DOCX, or TXT. Docling handles tables natively. Output reports are CSV (stdlib).

**Rules produced:**
- Supported input formats are PDF, DOCX, TXT only
- Report output is CSV (stdlib csv) — not Excel
- `openpyxl` is not a project dependency
- `DocumentFormat` enum has three values: PDF, DOCX, TXT

### Decision: sentence-transformers replaced by fastembed

`sentence-transformers` pulls PyTorch (~500 MB). Replaced with `fastembed` (ONNX Runtime backend). Same model weights, same output shape, ~50 MB install.

**Rules produced:**
- Use `fastembed` for all local embedding and reranking — never `sentence-transformers`
- Prefer ONNX Runtime over PyTorch for inference-only workloads
