# Enterprise AI Platform — Documentation Index

**Read this first.** Navigate to the component you're working on.

---

## Quick Links

| I need to...                        | Read                                          |
|-------------------------------------|-----------------------------------------------|
| Start coding                        | [SETUP.md](guides/SETUP.md)                   |
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

- **Supported formats:** PDF, DOCX, TXT only. No Excel/ZIP. [See memory](../.claude/projects/-home-kranthi-Projects-enterprise-ai/memory/project_supported_formats.md)
- **Embedding library:** fastembed (ONNX), not sentence-transformers. [See memory](../.claude/projects/-home-kranthi-Projects-enterprise-ai/memory/project_fastembed_rule.md)
- **Guardrails in MVP:** 7 of 14 guardrails. [See memory](../.claude/projects/-home-kranthi-Projects-enterprise-ai/memory/project_guardrails_plan.md)

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
