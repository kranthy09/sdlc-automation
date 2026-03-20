# DYNAFIT Layer 3 — Delivery Plan

## Context

Layer 2 is complete (13 platform utilities). Layer 3 builds the 5-phase DYNAFIT LangGraph pipeline
in `modules/dynafit/`. Two platform guardrail utilities (Session A) must be built first — they are
Layer 2 extensions consumed by Phase 1. The user asked for a 5-phase delivery plan with 1-3h tasks
and independent session documents so each session can be executed without needing prior conversation context.

Architectural source of truth: `docs/architecturalflows/`, `docs/specs/dynafit.md`, `docs/specs/guardrails.md`.
Guardrail mapping: `memory/project_guardrails_plan.md`.

---

## Delivery Phase 1: Foundation + Ingestion
**Sessions: A (guardrail utils) + B (module scaffold) + C (Phase 1 node)**
**Testable milestone:** Upload a DOCX/PDF/TXT → get `list[RequirementAtom]` with guardrails applied

### Session A — Platform Guardrail Utilities (2 tasks)
| # | Task | File(s) | Est |
|---|------|---------|-----|
| A1 | `FileValidationResult` + `InjectionScanResult` schemas; `file_validator.py` (G1-lite: MIME + size + SHA-256) | `platform/schemas/guardrails.py`, `platform/guardrails/file_validator.py` | 1–2h |
| A2 | `injection_scanner.py` (G3-lite: regex only, ~10 patterns, PASS/FLAG/BLOCK scoring) + unit tests for both | `platform/guardrails/injection_scanner.py`, `tests/unit/test_file_validator.py`, `tests/unit/test_injection_scanner.py` | 1–2h |

### Session B — Module Scaffold + LangGraph Graph (2 tasks)
| # | Task | File(s) | Est |
|---|------|---------|-----|
| B1 | `DynafitState` TypedDict; module package structure; `nodes/` + `prompts/` directories | `modules/dynafit/state.py`, package `__init__` files | 1–2h |
| B2 | LangGraph graph: 5 phase nodes wired in sequence; PostgreSQL checkpointer; `compile()` + smoke test | `modules/dynafit/graph.py`, `tests/integration/test_dynafit_graph.py` | 1–2h |

### Session C — Phase 1 Ingestion Node (3 tasks)
| # | Task | File(s) | Est |
|---|------|---------|-----|
| C1 | Doc parser: format detection → Docling → table extractor + prose splitter (parallel) | `modules/dynafit/nodes/phase1_ingestion.py` (parser block) | 2–3h |
| C2 | Requirement extractor (LLM → `RequirementAtom[]`) + normalizer (schema alignment) | same node, extractor + normalizer block | 2–3h |
| C3 | Validator + G1/G3 guardrail calls + emit `PhaseStartEvent` to Redis | same node, guardrail + event block; `tests/integration/test_phase1.py` | 1–2h |

---

## Delivery Phase 2: Knowledge Retrieval (RAG)
**Session D**
**Testable milestone:** Given a `RequirementAtom`, returns ranked D365 capability candidates

### Session D — Phase 2 RAG Node (3 tasks)
| # | Task | File(s) | Est |
|---|------|---------|-----|
| D1 | Vector store query (embedding → Qdrant) + BM25 search via `platform/retrieval/bm25.py` | `modules/dynafit/nodes/phase2_rag.py` | 1–2h |
| D2 | Reciprocal Rank Fusion of vector + BM25 results; reranker pass via `platform/retrieval/reranker.py` | same node, fusion block | 1–2h |
| D3 | Historical fitments retrieval + context assembly → `RetrievalContext`; integration test with seed KB | same node, context block; `tests/integration/test_phase2.py` | 1–2h |

---

## Delivery Phase 3: Semantic Matching
**Session E**
**Testable milestone:** Returns `MatchResult` with confidence tier and top-K D365 candidates

### Session E — Phase 3 Matching Node (3 tasks)
| # | Task | File(s) | Est |
|---|------|---------|-----|
| E1 | Cosine similarity computation; score normalisation against candidate pool | `modules/dynafit/nodes/phase3_matching.py` | 1–2h |
| E2 | Confidence scorer: composite score formula (embedding + BM25 + reranker weights) + threshold tiers | same node, scorer block | 1–2h |
| E3 | Candidate ranker (Top-K) + confidence tier assignment; golden fixture integration tests | same node, ranker block; `tests/integration/test_phase3.py` | 1–2h |

---

## Delivery Phase 4: LLM Classification
**Session F**
**Testable milestone:** Returns `ClassificationResult` (FIT / PARTIAL_FIT / GAP + confidence + rationale)

### Session F — Phase 4 Classification Node + Guardrails (4 tasks)
| # | Task | File(s) | Est |
|---|------|---------|-----|
| F1 | Jinja2 prompt templates (G8 firewall: autoescape, StrictUndefined, allowed-template whitelist) | `modules/dynafit/prompts/classification_v1.j2`, `modules/dynafit/prompts/rationale_v1.j2` | 1–2h |
| F2 | Short-circuit GAP check (no candidates → skip LLM); LLM reasoning: decompose → assess-each → aggregate | `modules/dynafit/nodes/phase4_classification.py` | 2–3h |
| F3 | XML response parser (xml.etree → regex fallback); G9 output schema (`strict=True` Pydantic); retry up to 2× → `REVIEW_REQUIRED` | same node, parser + validation block | 1–2h |
| F4 | Sanity checks (score-vs-verdict consistency); golden fixture tests (FIT/PARTIAL/GAP known outcomes) | same node, sanity block; `tests/integration/test_phase4.py` | 1–2h |

---

## Delivery Phase 5: Validation, HITL + Output
**Session G (backend) + minimal Layer 4 frontend**
**Testable milestone:** Full pipeline end-to-end — file in, HITL roundtrip, FDD CSVs out

### Session G — Phase 5 Validation + HITL Backend (4 tasks)
| # | Task | File(s) | Est |
|---|------|---------|-----|
| G1 | G10-lite sanity gate (3 rules: high-confidence-GAP, low-score-FIT, schema-retry-exhausted) | `modules/dynafit/guardrails.py` | 1–2h |
| G2 | Confidence filter node (auto-approve ≥0.85, flag 0.60–0.85, mandatory review <0.60) | `modules/dynafit/nodes/phase5_validation.py` (filter block) | 1–2h |
| G3 | LangGraph `interrupt()` HITL checkpoint; PostgreSQL state freeze/resume; `PhaseStartEvent` publish | same node, HITL block | 1–2h |
| G4 | Output builder: merge overrides → `ValidatedFitmentBatch` → FDD FOR FITS / FDD FOR GAPS; emit `CompleteEvent` | same node, output block; `tests/integration/test_phase5.py` | 1–2h |

### Layer 4 HITL Surface (2 tasks — minimal, no full API layer)
| # | Task | File(s) | Est |
|---|------|---------|-----|
| L4-1 | HITL API endpoints: `GET /batches/{id}/review` (serve flagged), `POST /batches/{id}/review/{atom_id}` (submit override) | `api/routes/review.py` | 2–3h |
| L4-2 | React review queue: list flagged items (req text + AI verdict + confidence), override form (new verdict + reason), submit → resume pipeline | `ui/src/components/ReviewQueue.tsx` | 2–3h |

---

## Session Documents to Create

One spec file per session. Each doc contains: goal, files to create, platform utilities to call, guardrails to integrate, test cases required, done criteria.

```
docs/sessions/session_A_guardrail_utilities.md
docs/sessions/session_B_module_scaffold.md
docs/sessions/session_C_phase1_ingestion.md
docs/sessions/session_D_phase2_rag.md
docs/sessions/session_E_phase3_matching.md
docs/sessions/session_F_phase4_classification.md
docs/sessions/session_G_phase5_validation.md
```

---

## Build Order Rules (unchanged)

- One session per conversation. Confirm the single named session before writing code.
- Never skip a session. Sessions within a phase can parallelize only if they have no state dependency.
- Phase 1 is a hard prerequisite for all later phases (state schema defined in Session B).
- Session A must complete before Session C (G1/G3 called in Phase 1 node).
- Layer 4 HITL surface (L4-1, L4-2) can be built in parallel with Session G or immediately after.

---

## Verification (end-to-end)

```bash
make validate-contracts       # dependency direction check
make test-unit                # all unit tests including guardrails
make test-integration         # all integration tests with Docker services
# Manual: POST /batches with sample D365 requirements DOCX
# Observe: pipeline runs, flags low-confidence items, HITL review resolves them,
#          FDD FOR FITS + FDD FOR GAPS CSVs download
```
