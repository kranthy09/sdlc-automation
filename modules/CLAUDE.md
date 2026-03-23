# modules/ — Layer 3

Every module follows the 6-file pattern. No exceptions.

## 6-File Pattern

```
modules/{name}/
├── manifest.yaml     # Self-registration: id, version, input/output schema refs
├── graph.py          # build_{name}_graph() — the ONLY public entry point
├── schemas.py        # State TypedDict (LangGraph state accumulator)
├── nodes.py          # Phase nodes — thin, call platform/ and agents/ only
├── prompts/          # Jinja2 templates — one per phase/step
└── tests/            # test_phase{N}_{topic}.py per phase
```

## Module Rules

- Nodes call `platform/` utilities. They **never** import `anthropic`, `qdrant_client`, or `sqlalchemy` directly.
- Nodes call `agents/` for reusable LangGraph logic.
- Modules **never** import from sibling modules (`modules/dynafit/` cannot import `modules/fdd/`).
- All product-variant parameters come from `ProductConfig`. No hardcoded model names, thresholds, or product IDs.
- `_get_embedder(product_id)` must receive `product_id` from state — never hardcode `"d365_fo"` or any product identifier.
- Every node function reads from state and writes back to state. No side effects beyond platform calls.

## Test Requirements

- Zero live LLM calls in the test suite — use `platform/testing/factories.py` mock LLM
- Zero direct infra instantiation — use mock factories for Qdrant, Postgres, Redis
- All LLM-dependent tests use golden fixtures from `tests/fixtures/golden/`
- `make test-module M={name}` must pass fully before the module is considered Layer 3 complete

## Guardrails — Built Alongside Each Phase Node

**Read `docs/specs/guardrails.md` before building any DYNAFIT phase node.**

Guardrails are not a separate layer. Each phase node owns its guardrail and they are built in the same session.

| Phase | Node file | Guardrail |
|-------|-----------|-----------|
| Pre-Layer 3 (Session A) | `platform/guardrails/file_validator.py` + `injection_scanner.py` | G1-lite + G3-lite — built first, called by Phase 1 |
| Phase 1 — Ingestion | `nodes/ingestion.py` | G1-lite, G3-lite, then G2 PII redaction (before LLM atomization) |
| Phase 4 — Classification | `nodes/classification.py` | G8 (Jinja2 template) + G9 (Pydantic strict) + G11 response PII scan (after LLM) |
| Phase 5 — Validation | `nodes/phase5_validation.py` + `guardrails.py` | G10-lite sanity gate + `response_pii_leak` flag + HITL via `interrupt()` + CSV-only output (no ZIP) |

HITL is mandatory at Phase 5. The node MUST call `interrupt()` when `flagged_for_review` is non-empty. Batch completion is blocked until a human resolves every flagged item.
