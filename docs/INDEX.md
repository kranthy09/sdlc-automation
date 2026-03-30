# Enterprise AI Platform — Documentation Index

**Read this first.** Navigate to the component you're working on.

---

## Quick Links

| I need to...                        | Read                                          |
|-------------------------------------|-----------------------------------------------|
| Start coding                        | [SETUP.md](guides/SETUP.md)                   |
| Understand build discipline         | [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) |
| Learn why we chose X over Y         | [DECISIONS.md](DECISIONS.md)                  |
| Understand a component              | [Components](#components) below               |
| Learn patterns for building code    | [PATTERNS.md](guides/PATTERNS.md)             |
| Look up a term                      | [GLOSSARY.md](reference/GLOSSARY.md)          |
| Debug an error                      | [ERRORS.md](reference/ERRORS.md)              |
| Review schemas/data structures      | [SCHEMAS.md](reference/SCHEMAS.md)            |

---

## Components

### Platform Layer

**Layer 1+2: Shared infrastructure.** No imports from `agents/`, `modules/`, `api/`.

| Component | Doc | Code |
|-----------|-----|------|
| **Schemas** | [schemas.md](components/platform/schemas.md) | `platform/schemas/` |
| **Config** | [config.md](components/platform/config.md) | `platform/config/` |
| **LLM Client** | [llm_client.md](components/platform/llm_client.md) | `platform/llm/client.py` |
| **Retrieval** | [retrieval.md](components/platform/retrieval.md) | `platform/retrieval/` |
| **Guardrails** | [guardrails.md](components/platform/guardrails.md) | `platform/guardrails/` |
| **Storage** | [storage.md](components/platform/storage.md) | `platform/storage/` |
| **Observability** | [observability.md](components/platform/observability.md) | `platform/observability/` |

### REQFIT Module (Layer 3)

**Phase nodes, guardrails, prompts.**

| Component | Doc | Code |
|-----------|-----|------|
| **Phase 1: Ingestion** | [phase1_ingestion.md](components/modules/phase1_ingestion.md) | `modules/dynafit/nodes/phase1_ingestion.py` |
| **Phase 2: RAG** | [phase2_rag.md](components/modules/phase2_rag.md) | `modules/dynafit/nodes/phase2_rag.py` |
| **Phase 3: Matching** | [phase3_matching.md](components/modules/phase3_matching.md) | `modules/dynafit/nodes/phase3_matching.py` |
| **Phase 4: Classification** | [phase4_classification.md](components/modules/phase4_classification.md) | `modules/dynafit/nodes/phase4_classification.py` |
| **Phase 5: Validation** | [phase5_validation.md](components/modules/phase5_validation.md) | `modules/dynafit/nodes/phase5_validation.py` |
| **Graph** | [graph.md](components/modules/graph.md) | `modules/dynafit/graph.py` |

### API Layer (Layer 4)

**FastAPI endpoints, Celery tasks.**

| Component | Doc | Code |
|-----------|-----|------|
| **Batch API** | [api_batches.md](components/api/api_batches.md) | `api/routes/batches.py` |
| **Task Queue** | [api_tasks.md](components/api/api_tasks.md) | `api/tasks/` |

---

## Decision Records

Why certain choices were made. Read when understanding architecture.

All decisions documented in [DECISIONS.md](DECISIONS.md):
- **Supported formats:** PDF, DOCX, TXT only. No Excel/ZIP.
- **PDF parser:** pdfplumber — table detection + prose isolation + OCR fallback. Not pypdf or Docling.
- **PARTIAL_FIT UI:** Configuration Steps section always visible in results view (placeholder shown when LLM returns null).
- **Embedding library:** fastembed (ONNX), not sentence-transformers.
- **MVP Guardrails:** 7 of 14 guardrails in MVP, 7 deferred to post-MVP.
- **HITL:** Human-in-the-loop at Phase 5 is mandatory.
- **Phases:** 5 sequential phases with checkpoints.

---

## Rules Before Writing Code

1. **One component per session.** Confirm scope before coding.
2. **Read** [docs/specs/rules.md](specs/rules.md) — import boundaries, coding standards, CI gates.
3. **Dependency rule:** `api/ → modules/ → agents/ → platform/`. Never sideways.
4. **Run** `make lint`, `make test`, `make validate-contracts` before pushing.

---

## Search Tips

```bash
# Find a component's doc
find docs/components -name "*phase1*"

# Find code location
grep -r "class FileValidator" platform/

# Validate setup
make validate-contracts
```
