# DYNAFIT Layer 3 — Delivery Plan

> One session per conversation. Confirm the named session. Read `docs/specs/dynafit.md` + `docs/specs/guardrails.md` before writing any node.

## Build Order

| Session | Deliverable | Guardrails | Key constraint |
|---------|-------------|------------|----------------|
| **A** | `platform/guardrails/file_validator.py` + `injection_scanner.py` (G1-lite, G3-lite) | G1, G3 | No new libs; before Session C |
| **B** | `modules/dynafit/state.py` + `graph.py` — LangGraph skeleton, Postgres checkpointer | — | Before all phase nodes |
| **C** | `nodes/phase1_ingestion.py` — file → `list[RequirementAtom]` | Calls G1, G3 | After A + B |
| **D** | `nodes/phase2_rag.py` — atoms → `RetrievalContext` (vector + BM25 + rerank + history) | — | After C |
| **E** | `nodes/phase3_matching.py` — context → `MatchResult` (composite score, Top-K, confidence tier) | — | After D |
| **F** | `nodes/phase4_classification.py` + Jinja2 templates — `ClassificationResult` FIT/PARTIAL/GAP | G8 (prompt firewall), G9 (output schema) | After E |
| **G** | `nodes/phase5_validation.py` + `modules/dynafit/guardrails.py` — G10-lite, HITL `interrupt()`, output builder → `ValidatedFitmentBatch` | G10-lite | After F |
| **L4** | `api/routes/review.py` + `ui/src/components/ReviewQueue.tsx` — HITL endpoints + review UI | — | Parallel with G or after |

## Verification

```bash
make validate-contracts   # before Session B
make test-unit            # each session adds tests
make test-integration     # Docker required (Postgres + Qdrant + Redis)
```

## MVP Guardrails Only
G1-lite, G3-lite (Session A) · G8, G9 (Session F) · G10-lite (Session G)

Post-MVP (skip): G2 PII/Presidio · G4 scope fence · G5 KB integrity · G6 context cap · G7 score bounds · G11–G14 · RBAC · rate limiter
