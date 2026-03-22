# Architecture

## Layer Diagram

```
enterprise_ai/
├── platform/              # Layer 1+2: shared infra — zero imports from above
│   ├── schemas/           # Pydantic contracts (Layer 1) — the glue between all layers
│   ├── config/            # Pydantic Settings — no hardcoded values anywhere
│   ├── observability/     # structlog logger, Prometheus metrics
│   ├── llm/               # Claude wrapper: retry, structured output, cost tracking
│   ├── retrieval/         # Embedder, Qdrant hybrid search, BM25, cross-encoder reranker
│   ├── parsers/           # Format detector, document parsers
│   ├── storage/           # PostgreSQL async, Redis pub/sub
│   └── testing/           # Mock factories shared by all module test suites
├── knowledge_bases/       # Product data: YAML + JSONL only — never Python
│   └── d365_fo/           # seed_data/, country_rules/, fdd_templates/
├── agents/                # Reusable LangGraph nodes — no product knowledge
├── modules/               # Business modules — one per product/workflow
│   └── dynafit/           # 6-file pattern: manifest, graph, schemas, nodes, prompts/, tests/
├── api/                   # FastAPI + Celery — dispatchers only, zero business logic
├── ui/                    # React + Vite
└── infra/                 # Docker Compose, Helm, scripts
```

## Dependency Law

```
api/ → modules/ → agents/ → platform/
```

- Never sideways: `modules/dynafit/` cannot import from `modules/fdd/`
- Never downward: `platform/` cannot import from `agents/`, `modules/`, or `api/`

## Team Ownership

| Directory | Owner | Rule |
|-----------|-------|------|
| `platform/` | Core platform team | No business logic, no product knowledge |
| `knowledge_bases/` | Each product team | D365 team owns `d365_fo/`. YAML + JSONL only. |
| `agents/` | Core platform team | Reusable across ALL modules |
| `modules/dynafit/` | D365 team | Calls `platform/` only. Never modifies `platform/`. |
| `api/` | Core platform team | Routes dispatch only. Zero logic. |

## ProductConfig — The Multi-Product Key

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

## DYNAFIT — 5 Phases

| Phase | Node | Input | Output |
|-------|------|-------|--------|
| 1 | Ingestion | Raw docs | RequirementAtom[] |
| 2 | RAG retrieval | RequirementAtom | AssembledContext |
| 3 | Semantic matching | AssembledContext | MatchResult |
| 4 | LLM classification | MatchResult | ClassificationResult |
| 5 | Validation + HITL | ClassificationResult[] | ValidatedFitmentBatch |

State accumulates in `RequirementState` TypedDict. Checkpointed to PostgreSQL after every node.
HITL pause via `interrupt_before=["validate"]` at Phase 5.

## Production Failure Modes (Resolved in Platform)

| Failure | Resolution | Location |
|---------|-----------|----------|
| Node crash mid-batch | PostgresSaver checkpoints. LangGraph resumes from last node. | `modules/dynafit/graph.py` |
| Qdrant timeout | 5s timeout, proceed with available results, flag `retrieval_confidence=LOW` | `platform/retrieval/vector_store.py` |
| LLM malformed output | XML → regex → Pydantic. 2 retries with error injected. Failure = REVIEW_REQUIRED. | `platform/llm/client.py` |
| Celery worker dies | `max_retries=2`, LangGraph resumes from PostgreSQL checkpoint | `api/workers/tasks.py` |
| WebSocket disconnect | Progress publishes to Redis regardless. Client reconnects, fetches via REST. | `api/websocket/progress.py` |
| LLM cost overrun | Prometheus counter per call. Grafana alert at threshold. | `platform/observability/metrics.py` |

## New Product Onboarding (Zero Platform Changes)

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
