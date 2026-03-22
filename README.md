# AI Platform

An AI agent platform for automating ERP implementation workflows.
Built as a layered monorepo — platform infrastructure first, product modules on top.

**Module 1: DYNAFIT** — Requirement Fitment Engine for Microsoft D365 F&O.
---

## Architecture

```
api/                    Layer 4 — FastAPI + Celery + WebSocket (thin dispatchers only)
modules/dynafit/        Layer 3 — DYNAFIT business module (D365 fitment)
agents/                 Layer 2 — Reusable LangGraph nodes (ingestion, RAG, classifier, validator)
platform/               Layer 1 — Shared infrastructure (LLM, retrieval, parsers, storage, observability)
knowledge_bases/        Product data — YAML + JSONL only, no Python
```

**Dependency rule:** `api → modules → agents → platform`. Never sideways, never downward.
Import boundaries are enforced by CI on every PR — violations block merges.

---

## Stack

| Concern          | Technology                                                  |
| ---------------- | ----------------------------------------------------------- |
| Orchestration    | LangGraph (state machine, checkpointing, HITL)              |
| LLM              | Claude Sonnet (Anthropic)                                   |
| Schemas          | Pydantic v2                                                 |
| Vector DB        | Qdrant + bge-small-en-v1.5 embeddings                       |
| Sparse retrieval | rank_bm25                                                   |
| Reranker         | Xenova/ms-marco-MiniLM (fastembed)                          |
| Storage          | PostgreSQL + pgvector, Redis                                |
| Document parsing | Docling (primary), Unstructured (fallback) — PDF, DOCX, TXT |
| API              | FastAPI + Celery + WebSocket                                |
| Observability    | structlog + Prometheus + Grafana                            |
| Package manager  | uv                                                          |
| Testing          | pytest + golden fixtures (zero live LLM calls in CI)        |

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) installed globally
- Docker + Docker Compose

Install uv globally (if not already):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

---

## Developer Setup

```bash
# 1. Clone
git clone <repo-url>
cd enterprise_ai

# 2. Create virtual environment and install all dependencies
uv venv --python 3.12
uv sync --all-extras

# 3. Activate the project venv
source .venv/bin/activate

# 4. Copy env and set your API key
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY at minimum

# 5. Install pre-commit hooks and spacy model
make setup
```

---

## Daily Developer Flow

```bash
# Enter project (each new terminal session)
cd ~/Projects/enterprise_ai
source .venv/bin/activate

# Start infrastructure (Qdrant, Postgres, Redis, Prometheus, Grafana)
make dev

# Run fast unit tests — no Docker required
make test-unit

# Run all tests — requires make dev
make test

# Full CI gate before committing (lint + contracts + test)
make ci

# Format code
make format

# Stop infrastructure
make dev-down
```

---

## All Make Commands

```bash
# Setup
make setup                        # uv sync + pre-commit install + spacy model

# Testing
make test                         # all tests with coverage
make test-unit                    # fast, no Docker
make test-integration             # requires Docker services
make test-module M=dynafit        # single module in isolation
make test-golden                  # golden fixture replay, no live LLM

# Quality
make lint                         # ruff + mypy --strict
make format                       # ruff auto-fix + format
make validate-contracts           # import boundary + manifest validation

# Infrastructure
make dev                          # docker compose up (all services)
make dev-down                     # docker compose down
make dev-logs                     # tail all service logs
make dev-ps                       # service status

# Knowledge base
make seed-kb PRODUCT=d365_fo      # embed capabilities into Qdrant
make seed-corpus PRODUCT=d365_fo  # crawl MS Learn docs into Qdrant (~45 min first run)

# Run
make run                          # FastAPI dev server on :8000
make ui                           # Vite dev server on :3000

# CI gate
make ci                           # lint + validate-contracts + test
```

---

## Infrastructure Ports

| Service    | URL                   | Credentials             |
| ---------- | --------------------- | ----------------------- |
| FastAPI    | http://localhost:8000 | —                       |
| Qdrant     | http://localhost:6333 | —                       |
| PostgreSQL | localhost:5432        | platform / dev_password |
| Redis      | localhost:6379        | —                       |
| Prometheus | http://localhost:9090 | —                       |
| Grafana    | http://localhost:3001 | admin / admin           |

---

## Adding a New Product Module

New product teams touch **only** these paths — zero changes to platform, agents, or api:

```
knowledge_bases/<product_id>/product_config.yaml
knowledge_bases/<product_id>/seed_data/capabilities.jsonl
knowledge_bases/<product_id>/seed_data/header_synonyms.yaml
knowledge_bases/<product_id>/country_rules/

modules/<module_name>/manifest.yaml
modules/<module_name>/graph.py
modules/<module_name>/schemas.py
modules/<module_name>/nodes.py
modules/<module_name>/prompts/
modules/<module_name>/tests/
```

Then:

```bash
make seed-kb PRODUCT=<product_id>
make validate-contracts
```

---

## CI Gates (all required, none skippable)

```bash
make lint               # ruff check + mypy --strict on platform/, agents/, modules/, api/
make validate-contracts # import boundary violations + manifest schema references
make test               # pytest with coverage (unit + integration against Docker services)
```

All three must pass on every PR. Live LLM calls are never in CI — all LLM tests use golden fixtures.

---

## Key Constraints

- `platform/` has zero knowledge of any product — no model names, no thresholds, no KB namespaces hardcoded
- Every layer boundary uses Pydantic v2 typed schemas — no free-text parsing
- All LLM prompt templates are Jinja2 files — no f-strings or string concatenation
- Retry logic lives exclusively in `platform/llm/client.py` — never duplicated in nodes
- Metrics and structured logging are added when writing a component, never as an afterthought
- New module onboarding requires zero Python changes to `platform/`, `agents/`, or `api/`

---

## Docs

| File                       | Purpose                                                     |
| -------------------------- | ----------------------------------------------------------- |
| `CLAUDE.md`                | Project pointer — build order, dependency rule, doc index    |
| `docs/specs/rules.md`     | Architecture, import boundaries, code standards, lessons     |
| `docs/specs/dynafit.md`   | DYNAFIT 5-phase algorithms, prompts, thresholds, library map |
| `docs/specs/api.md`       | API endpoints, WebSocket protocol, DB schema, React UI       |
| `docs/specs/guardrails.md`| MVP guardrails (7 active) + post-MVP roadmap (7 deferred)   |
| `docs/specs/tdd.md`       | Testing philosophy, golden fixtures, build order             |
| `docs/architecturalflows/`| SVG architecture diagrams                                   |
