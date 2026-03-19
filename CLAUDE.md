# Enterprise AI Platform — CLAUDE.md

> **This is the project intelligence file. Claude Code reads this first.**
>
> | File | When to read |
> |------|-------------|
> | `DYNAFIT_IMPLEMENTATION_SPEC.md` | When building Layer 3 (modules/dynafit/) — algorithms, thresholds, prompts |
> | `FRONTEND_BACKEND_SPEC.md` | When building Layer 4 (api/, ui/) — endpoints, WebSocket, DB schema |
> | `TDD_IMPLEMENTATION_GUIDE.md` | For TDD patterns, Docker setup, golden fixtures, week-by-week execution |
> | `VSCODE_CLAUDE_CODE_SETUP.md` | Dev environment setup, VS Code config, Claude Code prompting patterns |

---

## What This Project Is

An enterprise AI agent platform for automating ERP implementation workflows.
**Module 1: DYNAFIT** — Requirement Fitment Engine for D365 F&O — is the first module.
10+ modules across D365, Power Platform, Azure, Salesforce, SAP will follow, contributed by different teams and clients.

**DYNAFIT is the proof-of-concept that validates the platform. It is not the platform.**

---

## Build Philosophy — Read Before Writing Any Code

### Platform First. Product Second.

The business starting point is DYNAFIT. The engineering starting point is `platform/`.

If you build DYNAFIT before the platform, the next team (SAP, Salesforce, another client) forks it and you have two codebases. If you build the platform *proven by* DYNAFIT, every team that follows gets infrastructure for free.

**DYNAFIT is the first consumer of the platform, not the thing being built.**

### The Invariant That Must Hold Forever

> A new product team onboards by creating files in `knowledge_bases/` and `modules/`.
> They make **zero changes** to `platform/`, `agents/`, or `api/`.

If onboarding product #2 requires touching `platform/`, the abstraction is wrong.
Fix the platform before adding more products. Never work around it.

### Failure Modes, Not Happy Paths

Every component is designed for failure first. Before implementing any phase node, answer:
1. What happens when this external dependency is unavailable?
2. What happens when the LLM returns malformed output?
3. What happens when the process dies mid-execution?

These answers are architectural decisions made in `platform/`, not patches added to nodes later.

---

## Team Ownership Model

```
platform/          ← Core platform team. No business logic. No product knowledge.
knowledge_bases/   ← Individual product teams. D365 team owns d365_fo/. SAP team owns sap_s4hana/.
agents/            ← Core platform team. Reusable across ALL modules.
modules/dynafit/   ← D365 team. Calls platform/ only. Never modifies platform/.
modules/<next>/    ← Next product team. Same rule.
api/               ← Core platform team. Thin routing only. Zero business logic.
ui/                ← Core/frontend team. Consumes api/ only.
infra/             ← Core platform team.
tests/             ← Shared. Unit and integration infrastructure.
```

This is a team contract enforced by CI, not a folder convention.

---

## Architecture — 4-Layer Monorepo

```
enterprise-ai-platform/
├── platform/              # Layer 1: shared infra — zero imports from above layers
│   ├── schemas/           # Pydantic contracts — the glue between all layers and phases
│   ├── llm/               # LLM client, retry, structured output, cost tracking
│   ├── retrieval/         # Embedder, Qdrant hybrid search, BM25, cross-encoder reranker
│   ├── parsers/           # Format detector, Excel (openpyxl), PDF/DOCX (Docling)
│   ├── storage/           # PostgreSQL async (SQLAlchemy), Redis pub/sub
│   ├── observability/     # structlog JSON logger, Prometheus metrics
│   ├── config/            # Pydantic Settings, ProductConfig
│   └── testing/           # Shared mock factories, fixtures (used by all module test suites)
├── knowledge_bases/       # Product data: YAML + JSONL only, never Python
│   └── d365_fo/
│       ├── product_config.yaml
│       ├── seed_data/         # capabilities.jsonl, header_synonyms.yaml, term_aligner.yaml
│       ├── country_rules/     # DE.yaml, FR.yaml, ...
│       └── fdd_templates/     # fit_template.j2
├── agents/                # Layer 2: reusable LangGraph nodes — no product knowledge
│   ├── ingestion/
│   ├── rag/
│   ├── classifier/
│   └── validator/
├── modules/               # Layer 3: business modules — one per product/workflow
│   └── dynafit/           # 6-file pattern (see below)
├── api/                   # Layer 4: FastAPI + Celery — dispatches only, no logic
│   ├── routes/
│   ├── workers/
│   └── websocket/
├── ui/                    # React + Vite dashboard
├── infra/                 # Docker Compose, Helm, scripts
│   ├── docker/
│   ├── helm/
│   └── scripts/           # seed_knowledge_base.py, validate_contracts.py
├── tests/                 # Shared test infrastructure
│   ├── unit/
│   ├── integration/
│   └── fixtures/golden/
└── docs/                  # Architecture docs, ADRs, runbooks
    ├── adr/
    └── runbooks/
```

**Dependency rule:** `api/ → modules/ → agents/ → platform/`
Never sideways (between modules). Never downward (platform cannot import agents).
CI rejects violations on every PR.

---

## Build Order — Layer by Layer

This is the sequence. Do not skip layers. Do not build out of order.

---

### Layer 0 — Scaffold + CI

**Goal:** `make ci` passes on an empty codebase before any logic exists.

**Why first:** CI runs from day 1. Import violations caught at PR time, not after three modules are built. Docker services available immediately so integration tests can run from the first integration test written.

**Deliverables:**

```
monorepo directory structure + __init__.py in every Python package
pyproject.toml                    # uv, all deps declared upfront
Makefile                          # single command interface (see Commands section)
.github/workflows/ci.yml          # runs: make lint, make test, make validate-contracts
infra/docker/docker-compose.yaml  # Qdrant, PostgreSQL+pgvector, Redis, Prometheus, Grafana
infra/scripts/validate_contracts.py  # import boundary check + manifest schema validator
pre-commit hooks                  # ruff, mypy
```

**validate_contracts.py enforces (on every PR):**
- Nothing in `platform/` imports from `agents/`, `modules/`, or `api/`
- Nothing in `agents/` imports from `modules/` or `api/`
- Nothing in `modules/X/` imports from `modules/Y/` (no cross-module imports ever)
- Nothing in `api/` imports from `modules/` except graph entry points and schema types
- All `manifest.yaml` `input_schema` and `output_schema` fields resolve to real classes in `platform/schemas/`

**Layer 0 complete when:** `make dev` starts all Docker services. `make ci` runs without error.

---

### Layer 1 — Platform Schemas

**Goal:** Every Pydantic model that crosses a layer or phase boundary exists, is typed, and is tested.

**Why second:** Schemas are the executable specification. Teams build against them in parallel. Writing them forces precision that documents cannot.

**Build in this exact order:**

```
platform/schemas/base.py          # PlatformModel: frozen=True, str_strip_whitespace, validate_default
platform/schemas/product.py       # ProductConfig — THE multi-product key (see below)
platform/schemas/requirement.py   # RawUpload, RequirementAtom, ValidatedAtom, FlaggedAtom
platform/schemas/retrieval.py     # RetrievalQuery, AssembledContext, RankedCapability, PriorFitment
platform/schemas/fitment.py       # MatchResult, ClassificationResult, ValidatedFitmentBatch
platform/schemas/events.py        # WebSocket message types: phase_start, step_progress, classification, complete, error
platform/schemas/errors.py        # UnsupportedFormatError, ParseError, RetrievalError — typed, not raw strings
```

**ProductConfig is the most critical schema** — the handshake between product teams and the platform:

```python
class ProductConfig(PlatformModel):
    product_id: str
    display_name: str
    llm_model: str                          # "claude-sonnet-4-20250514"
    embedding_model: str                    # "BAAI/bge-large-en-v1.5"
    capability_kb_namespace: str            # Qdrant collection name
    doc_corpus_namespace: str
    historical_fitments_table: str          # PostgreSQL table name
    fit_confidence_threshold: float         # 0.85
    review_confidence_threshold: float      # 0.60
    auto_approve_with_history: bool
    country_rules_path: str
    fdd_template_path: str
    code_language: str                      # "xpp", "abap", "apex"
```

Every parameter that varies by product lives in ProductConfig.
Nodes receive a ProductConfig instance. They never hardcode model names or thresholds.

**Layer 1 complete when:** Schema tests cover valid cases, invalid cases, and cross-field validation. `mypy --strict` passes on all schema files.

---

### Layer 2 — Platform Utilities

**Goal:** All shared infrastructure components exist, are tested, and emit observability from birth.

**Why third:** Every module consumes these. They must be stable before any module is built.

**Build in this order** (each depends on the previous being stable):

```
platform/config/settings.py         # Pydantic Settings, reads from env — no hardcoded values anywhere
platform/observability/logger.py    # structlog JSON, correlation_id binding — imported by everything else
platform/observability/metrics.py   # Prometheus counters/histograms: llm_calls, phase_latency, cost_usd
platform/llm/client.py              # Claude wrapper: structured output, 2-retry with error injection, cost emit, @traceable
platform/retrieval/embedder.py      # bge-large-en-v1.5, batch encode, L2 normalize, in-process cache
platform/retrieval/vector_store.py  # Qdrant hybrid search behind an interface (not Qdrant-specific contract)
platform/retrieval/bm25.py          # rank_bm25 sparse retrieval
platform/retrieval/reranker.py      # cross-encoder/ms-marco-MiniLM, adaptive K selection, sigmoid activation
platform/parsers/format_detector.py # 3-layer: magic bytes → ZIP inspection → python-magic fallback
platform/parsers/excel_parser.py    # openpyxl: visible sheets, merged cells, multi-row headers, noise rows
platform/parsers/docling_parser.py  # Docling primary → Unstructured.partition_auto() fallback
platform/parsers/image_extractor.py # size filter → Haiku type classifier → Sonnet vision extraction → ImageDerivedChunk
platform/storage/postgres.py        # async SQLAlchemy models, pgvector cosine queries
platform/storage/redis_pub.py       # publish/subscribe abstraction for progress event streaming
platform/testing/factories.py       # Mock LLM client, mock Qdrant, mock Redis — shared by all module tests
```

**Non-negotiable rules for this layer:**
- LLM retry logic lives in `platform/llm/client.py` only — never duplicated in any node
- `platform/observability/logger.py` is the first import in every other platform component
- `platform/observability/metrics.py` emits at every external call (LLM, Qdrant, Postgres, Redis)
- `platform/retrieval/vector_store.py` exposes an interface, not Qdrant types — swappable
- `platform/testing/factories.py` provides all mocks — module tests never instantiate infrastructure

**Layer 2 complete when:** `make test-unit` passes for all platform components. `make test-integration` passes against live Docker services.

---

### Layer 3 — DYNAFIT Module

**Goal:** First product module. Proves the platform works end-to-end. Consumes `platform/` and `agents/` only.

**When to read:** Read `DYNAFIT_IMPLEMENTATION_SPEC.md` in full before writing any node. Every algorithm, threshold, and prompt template is specified there.

**Deliverables:**

```
modules/dynafit/manifest.yaml       # Self-registration: id, version, input/output schema refs
modules/dynafit/schemas.py          # RequirementState TypedDict (LangGraph state accumulator)
modules/dynafit/graph.py            # build_dynafit_graph() — the ONLY public entry point
modules/dynafit/nodes.py            # phase1_node through phase5_node (thin, call agents/)
modules/dynafit/prompts/
│   ├── phase1_atomizer.j2
│   ├── phase1_intent_classifier.j2
│   ├── phase1_module_tagger.j2
│   └── phase4_classification.j2
modules/dynafit/tests/
│   ├── test_phase1_ingestion.py
│   ├── test_phase2_retrieval.py
│   ├── test_phase3_matching.py
│   ├── test_phase4_classification.py
│   └── test_phase5_validation.py
knowledge_bases/d365_fo/            # all data — no Python
```

**Correct node pattern — nodes call platform, never infrastructure directly:**

```python
# WRONG — node owns infrastructure
from anthropic import Anthropic
client = Anthropic()
response = client.messages.create(...)

# RIGHT — node calls platform utility
from platform.llm.client import classify
result = classify(prompt, output_schema=ClassificationResult, config=product_config)
```

**Layer 3 complete when:** `make test-module M=dynafit` passes all phase tests with golden fixtures. Zero live LLM calls in the test suite. Zero direct infrastructure imports in `nodes.py`.

---

### Layer 4 — API + Workers + UI

**Goal:** The serving layer. Thin dispatchers only. Proves the loop closes end-to-end.

**When to read:** Read `FRONTEND_BACKEND_SPEC.md` in full before writing any route or UI component.

**Deliverables:**

```
api/main.py                         # FastAPI app, router mounting, health check
api/routes/dynafit.py               # POST /upload, POST /run, GET /results, review endpoints, GET /report
api/workers/tasks.py                # Celery task: invokes build_dynafit_graph(), emits Redis progress
api/websocket/progress.py           # subscribes Redis channel, forwards to WebSocket client
ui/src/                             # React + Vite (full structure in FRONTEND_BACKEND_SPEC.md)
```

**API rules:**
- Routes validate input schema → dispatch to Celery → return immediately (202 Accepted)
- Zero business logic in routes — if logic appears in a route, it moves to `modules/` or `platform/`
- Every route returns a typed Pydantic response model
- WebSocket handler only subscribes Redis and forwards — no computation

**Layer 4 complete when:** Full user journey test passes: file upload → 5-phase pipeline → human review → Excel report downloaded.

---

## Multi-Product Extensibility — The Onboarding Contract

When a new team (e.g., SAP S/4HANA) onboards:

**Step 1 — Knowledge base only, no code:**
```
knowledge_bases/sap_s4hana/product_config.yaml
knowledge_bases/sap_s4hana/seed_data/capabilities.jsonl
knowledge_bases/sap_s4hana/seed_data/header_synonyms.yaml
knowledge_bases/sap_s4hana/country_rules/DE.yaml
```

**Step 2 — New module, 6-file pattern, no platform changes:**
```
modules/fitment_sap/manifest.yaml   # input/output schema refs point to platform/schemas/
modules/fitment_sap/schemas.py
modules/fitment_sap/graph.py
modules/fitment_sap/nodes.py
modules/fitment_sap/prompts/
modules/fitment_sap/tests/
```

**Step 3 — Seed and validate:**
```bash
make seed-kb PRODUCT=sap_s4hana
make validate-contracts             # CI checks manifest refs are valid platform/ types
POST /api/v1/sap_s4hana/fitment/run
```

**Zero Python changes to `platform/`, `agents/`, or `api/`.**
If any platform change is needed, the platform team absorbs and generalizes it. The product team does not patch it.

---

## Production Reliability Decisions

Resolved at architecture level. Not patched into nodes.

| Failure Mode | Resolution | Where Implemented |
|---|---|---|
| Node crashes mid-batch | PostgresSaver checkpoints on every node completion. LangGraph resumes from last checkpoint on Celery retry. | `modules/dynafit/graph.py` (checkpointer) |
| Qdrant timeout during Phase 2 | 5s timeout per source. Proceed with available results. Flag `retrieval_confidence=LOW`. Pipeline never blocked. | `platform/retrieval/vector_store.py` |
| LLM returns malformed output | 3-layer parse: XML → regex → Pydantic. 2 retries with error injected into prompt. Failure = `REVIEW_REQUIRED`, not crash. | `platform/llm/client.py` |
| Celery worker dies | `max_retries=2`, `default_retry_delay=30`. LangGraph resumes from PostgreSQL checkpoint. Batch never lost. | `api/workers/tasks.py` |
| WebSocket client disconnects | Progress publishes to Redis regardless of client state. Client reconnects and fetches state via `GET /results`. | `api/websocket/progress.py` |
| LLM cost overrun | Prometheus counter on every call. Grafana alert at threshold. FAST_TRACK route minimizes calls for high-confidence matches. | `platform/observability/metrics.py` |
| Circular dependencies in requirements | NetworkX cycle detection in Phase 5. Fatal error surfaced to review queue, not swallowed silently. | `modules/dynafit/nodes.py` (phase5) |
| Vague requirements reaching LLM | Ambiguity detector (Phase 1 Step 4) rejects before any LLM call. Specificity score < 0.3 = REJECT. | `agents/ingestion/` |

---

## CI Enforcement

These checks run on every PR. They are not skippable.

```bash
make lint               # ruff check . + mypy --strict on platform/, agents/, modules/, api/
make test               # pytest --cov (unit + integration, against Docker services)
make validate-contracts # import boundary check + manifest schema validation
```

A PR that breaks any gate does not merge, regardless of urgency.

---

## Module 1: DYNAFIT — 5 Phases

Full specification in `DYNAFIT_IMPLEMENTATION_SPEC.md`. Every algorithm, threshold, and prompt is there.

| Phase | Node | Input | Output |
|-------|------|-------|--------|
| 1 | Ingestion | Raw docs (Excel/Word/PDF) | RequirementAtom[] |
| 2 | Knowledge retrieval (RAG) | RequirementAtom | AssembledContext |
| 3 | Semantic matching | AssembledContext | MatchResult |
| 4 | Classification (LLM) | MatchResult | ClassificationResult |
| 5 | Validation & output | ClassificationResult[] | ValidatedFitmentBatch |

Each phase = LangGraph node. State accumulates through `RequirementState` TypedDict.
Checkpointed to PostgreSQL after every node completion.
HITL pause via `interrupt_before=["validate"]` at Phase 5.

---

## Technology Stack

| Layer | Library | Purpose |
|-------|---------|---------|
| Orchestration | LangGraph | Agent state machine, checkpointing, HITL |
| Schemas | Pydantic v2 | Every boundary typed — input → transform → output |
| Document parsing | Docling (primary), Unstructured (fallback) | PDF/DOCX/PPTX → structured content |
| Excel parsing | openpyxl | Native merged-cell-aware extraction |
| OCR | Tesseract | Scanned docs, embedded images |
| Translation | Argos Translate | DE/FR/JP → EN (offline) |
| NLP | spaCy (en_core_web_lg) | NER, tokenization, EntityRuler |
| Fuzzy matching | RapidFuzz | Synonym/header matching |
| Dedup (small) | FAISS | Cosine similarity for <5K items |
| Dedup (large) | datasketch | MinHash LSH for >10K items |
| Vector DB | Qdrant | Capability KB + MS Learn corpus |
| Embeddings | bge-large-en-v1.5 | 1024-dim, runs local, MTEB top-5 |
| Sparse retrieval | rank_bm25 | Keyword matching alongside vectors |
| Reranker | cross-encoder/ms-marco-MiniLM | top-20 → top-5 precision |
| Historical store | PostgreSQL + pgvector | Prior wave decisions, audit trail |
| LLM | Claude Sonnet (primary) | Classification, rationale, FDD gen |
| Prompt templates | Jinja2 | Version-controlled, slot-filling |
| API | FastAPI | REST + WebSocket endpoints |
| Async workers | Celery + Redis | Background graph execution |
| Logging | structlog | Structured JSON logging |
| Tracing | LangSmith | LLM call traces, latency, token counts |
| Metrics | Prometheus + Grafana | Counters, histograms, cost dashboards |
| Reports | openpyxl | Fitment matrix Excel output |
| Testing | pytest + pytest-asyncio | Unit, integration, golden fixtures |
| Package manager | uv | Fast Python dependency management |
| UI | React + Vite + Tailwind | Dashboard, review queue |
| Containerization | Docker Compose (dev), Helm (prod) | Local and K8s deployment |

---

## Coding Standards

- **Python 3.12+**, type hints everywhere, `mypy --strict` must pass — no exceptions
- **Pydantic v2** at every module boundary — input schema → transform → output schema
- **No classes unless stateful** — prefer functions and typed protocols
- **structlog** for all logging — JSON, correlation IDs, phase context bound via `contextvars`
- **Prometheus metrics** at every phase boundary and every external call — never added as afterthought
- **pytest TDD** — write test before implementation (RED → GREEN → REFACTOR), always
- **Jinja2** for all LLM prompt templates — never f-strings, never string concatenation
- **Makefile** as the single command interface — no undocumented one-off commands
- Every module follows the **6-file pattern**: `manifest.yaml`, `graph.py`, `schemas.py`, `nodes.py`, `prompts/`, `tests/`

---

## File Naming Conventions

```
platform/schemas/{domain}.py                  # requirement, fitment, retrieval, events, errors, product
platform/{capability}/{component}.py          # llm/client, retrieval/embedder, parsers/excel_parser
agents/{capability}/agent.py                  # ingestion, rag, classifier, validator
modules/{name}/graph.py                       # entry point is always build_graph()
modules/{name}/prompts/{phase}_{step}.j2      # phase1_atomizer.j2, phase4_classification.j2
modules/{name}/tests/test_{phase}_{topic}.py  # test_phase1_ingestion.py
knowledge_bases/{product_id}/                 # all data files — no Python ever
tests/unit/test_{component}.py               # mirrors platform/ structure
tests/integration/test_{component}.py        # needs Docker services
tests/fixtures/golden/{phase}.json           # captured LLM responses for replay
```

---

## Commands (Makefile)

```makefile
# Setup
make setup                  # uv sync + pre-commit install + spacy model download

# Testing
make test                   # pytest --cov (all markers)
make test-unit              # fast, no Docker
make test-integration       # needs Docker services (make dev first)
make test-module M=dynafit  # single module in isolation
make test-golden            # golden fixture replay (no live LLM)

# Quality
make lint                   # ruff check . + mypy --strict
make validate-contracts     # import boundary + manifest validation

# Infrastructure
make dev                    # docker-compose up (Qdrant, Postgres, Redis, Prometheus, Grafana)
make dev-down               # docker-compose down
make seed-kb PRODUCT=d365_fo      # embed capabilities.jsonl into Qdrant (Source A)
make seed-corpus PRODUCT=d365_fo  # crawl MS Learn docs into Qdrant (Source B, ~45 min first run)

# Run
make run                    # FastAPI dev server (port 8000)
make ui                     # Vite dev server (port 3000)

# CI (all quality gates)
make ci                     # lint + test + validate-contracts
```

---

## Key Design Decisions

1. **Platform first, product second** — DYNAFIT is the platform's first consumer, not what's being built
2. **Knowledge bases are data, not code** — new products = YAML + JSONL, zero Python changes
3. **Modules self-register via `manifest.yaml`** — platform auto-discovers and routes; no central registry to update
4. **ProductConfig is the multi-product key** — all product-variant parameters live there, never hardcoded in nodes
5. **Import boundaries are CI-enforced hard rules** — violations block merges; no exceptions for urgency
6. **Every LLM call has structured output via Pydantic** — no free-text parsing anywhere in the codebase
7. **HITL via LangGraph `interrupt()`** — consultant overrides write to `historical_fitments` and improve future waves
8. **Retry logic lives in `platform/llm/client.py`, not nodes** — nodes call and trust it; duplication is banned
9. **Observability is infrastructure, not afterthought** — metrics and logging added in Layer 2, inherited by all consumers
10. **Golden fixtures for all LLM tests** — live LLM calls never appear in CI test suite

---

## What NOT to Do

**Architecture violations — CI will catch these:**
- Don't import between modules (`modules/dynafit/` cannot import from `modules/fdd/`)
- Don't import upward (`platform/` cannot import from `agents/` or `modules/`)
- Don't put business logic in `api/` — routes dispatch only
- Don't hardcode model names, thresholds, or KB namespaces in node code — all in ProductConfig

**Code quality violations:**
- Don't use f-strings for prompts — Jinja2 templates, version-controlled
- Don't skip Pydantic validation — every layer boundary must be typed
- Don't write retry logic in nodes — it belongs in `platform/llm/client.py`
- Don't add metrics or logging after the component is written — add them when writing it
- Don't call Qdrant, Anthropic, or PostgreSQL directly from nodes — call platform utilities

**Process violations:**
- Don't build DYNAFIT phases before Layer 2 (platform utilities) is stable and tested
- Don't skip Layer 0 CI setup — it runs from the first commit
- Don't defer observability — structlog and Prometheus are Layer 2 deliverables
- Don't build the UI before the API routes exist and are tested
- Don't onboard product #2 before DYNAFIT proves the extensibility contract holds
- Don't write integration tests that require a live LLM — use golden fixtures for all LLM calls in CI
