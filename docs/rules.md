# Rules — Read Before Writing Any Code

## Build Discipline

- **One component per session.** Before writing code, confirm: "What exactly are we building today?"
- **Only build what is explicitly requested** for the current phase. No anticipatory features.
- **Confirm scope** before starting. If the request is vague, ask. Don't infer and over-build.
- **Layer order is strict.** Layer 2 utility before any Layer 3 node. No exceptions.
- **MVP Testing:** Integration tests for core business workflows first. Unit tests only for complex business logic (validation rules, algorithms, error-path branching). Never test constructors, simple defaults, Pydantic built-ins (frozen, whitespace stripping), or every enum value — one valid + one invalid case is enough.

## Import Boundaries (CI-enforced)

```
platform/   cannot import from  agents/, modules/, api/
agents/     cannot import from  modules/, api/
modules/X/  cannot import from  modules/Y/  (no cross-module imports, ever)
api/        can only import from modules/ graph entry points and platform/schemas/
```

Violations block merges. `make validate-contracts` runs on every PR.

## Code Standards

- **Python 3.12+**, type hints everywhere, `mypy --strict` must pass
- **Pydantic v2** at every layer boundary — input schema → transform → output schema
- **Jinja2** for all LLM prompt templates — never f-strings or string concatenation
- **structlog** for all logging — JSON, correlation IDs, bound via `contextvars`
- **Prometheus metrics** at every external call (LLM, Qdrant, Postgres, Redis) — not added later
- **Retry logic lives only in `platform/llm/client.py`** — nodes call it, never duplicate it
- **No direct infra calls from nodes** — never import `anthropic`, `qdrant_client`, or `sqlalchemy` in `modules/`
- **No free-text LLM parsing** — every LLM call uses structured output via Pydantic

### Ruff-enforced patterns (must pass before every push)

| Rule | What it catches | Correct pattern |
|------|----------------|-----------------|
| **I001** | Unsorted / unformatted import blocks | Run `make format` — never hand-sort |
| **UP024** | Legacy OS-error aliases | `OSError` not `IOError` / `EnvironmentError` |
| **UP035** | Deprecated `typing` imports | `from collections.abc import Generator` not `from typing import Generator` |
| **UP047** | Generic functions using `TypeVar` | PEP 695: `def fn[T: Base](...)` not `T = TypeVar(...)` for standalone functions |
| **F401** | Unused imports | Delete them; add `# noqa: F401` only for deliberate side-effect imports |
| **B** | Bugbear traps | No mutable defaults, no bare `except:`, no `assert` in production paths |

`make format` auto-fixes I001, UP024, UP035. UP047 on standalone functions requires a manual rewrite to PEP 695 syntax. Run `make lint` to confirm zero errors before pushing.

## What Nodes Must Do

```python
# WRONG — node owns infrastructure
from anthropic import Anthropic
client = Anthropic()

# RIGHT — node calls platform utility
from platform.llm.client import classify
result = classify(prompt, output_schema=MySchema, config=product_config)
```

## CI Gates (all three must pass on every PR)

```bash
make lint               # ruff + mypy --strict
make test               # pytest --cov (unit + integration)
make validate-contracts # import boundary + manifest schema validation
```

No merge bypasses these. Not for urgency. Not for hotfixes.

## Golden Fixtures

- Live LLM calls never appear in CI test suite
- Capture real LLM responses once → replay in CI via `tests/fixtures/golden/`
- Mark tests with `@pytest.mark.golden`; mark live-LLM tests with `@pytest.mark.llm` (skipped in CI)
