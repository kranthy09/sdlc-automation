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
- All product-variant parameters come from `ProductConfig`. No hardcoded model names or thresholds.
- Every node function reads from state and writes back to state. No side effects beyond platform calls.

## Test Requirements

- Zero live LLM calls in the test suite — use `platform/testing/factories.py` mock LLM
- Zero direct infra instantiation — use mock factories for Qdrant, Postgres, Redis
- All LLM-dependent tests use golden fixtures from `tests/fixtures/golden/`
- `make test-module M={name}` must pass fully before the module is considered Layer 3 complete
