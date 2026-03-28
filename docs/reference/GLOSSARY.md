# Glossary — Terminology

## Core Concepts

**Requirement Atom** — Single, indivisible requirement extracted from a document. Has text, priority, module, country, source.

**Fitment** — Does D365 F&O support this requirement? Result: FIT, GAP, REVIEW_REQUIRED.

**Batch** — Group of documents processed together. Flows through 5 phases. Checkpoint at Phase 5 for human review.

**Phase** — One of 5 stages in REQFIT:
1. **Ingestion** — Extract requirements from documents
2. **RAG** — Retrieve similar requirements from knowledge base
3. **Matching** — Find D365 modules/features that might fulfill
4. **Classification** — Determine FIT/GAP/REVIEW
5. **Validation** — Human review (HITL) and audit

## System

**Guardrail** — Safety check. Blocks, flags, or passes. Woven into phase nodes.

**HITL** — Human-In-The-Loop. LangGraph interrupts at Phase 5, waits for human decision, resumes.

**Knowledge Base** — D365 F&O reference data. Module configs, features, FDD templates.

**Vector Store** — Qdrant. Hybrid search: dense embeddings + BM25 + cross-encoder reranking.

**Graph** — LangGraph DAG. Maps 5 phases as nodes. Checkpointed at each phase.

## Infrastructure

**Platform** — Layer 1+2. Shared: schemas, LLM client, retrieval, guardrails, storage, observability.

**Module** — Layer 3. Product logic. REQFIT is Module 1.

**Agent** — Reusable LangGraph nodes. No product knowledge.

**API** — Layer 4. FastAPI + Celery. Dispatchers only.

**UI** — React + Vite. Real-time phase progress, HITL review UI.

## Data

**RawUpload** — User-provided file (bytes + filename).

**DocumentFormat** — PDF, DOCX, or TXT.

**ProseChunk** — Paragraph extracted from document with heading/page/offset.

**Table Record** — Row from table with column headers mapped to canonical fields.

**ClassificationResult** — LLM output: classification (FIT/GAP), confidence, rationale.

**ValidatedFitmentBatch** — Final output after Phase 5. Includes overrides from human review.

## Standards

**Pydantic v2** — Data validation at every layer boundary. Strict mode enforced.

**Jinja2** — Template language for LLM prompts. Never f-strings.

**structlog** — Structured JSON logging. Auto-adds correlation ID.

**Prometheus** — Metrics. Already tracked at LLM, DB, Redis calls.

**mypy --strict** — Type checking. All code fully typed.

**Ruff** — Linter. I001 (imports), UP024 (OS errors), B (bugbear).
