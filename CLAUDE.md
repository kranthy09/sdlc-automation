# Enterprise AI Platform

Enterprise AI agent platform for automating ERP implementation workflows.
**DYNAFIT** (D365 F&O Requirement Fitment Engine) is Module 1 — the proof-of-concept that validates the platform.

---

## The Invariant That Must Never Break

> A new product team onboards by adding files to `knowledge_bases/` and `modules/`.
> They make **zero changes** to `platform/`, `agents/`, or `api/`.

If product #2 requires touching `platform/`, the abstraction is wrong. Fix it before adding more products.

---

## Layer Build Order

Build in this exact sequence. Never skip. Never build out of order.

```
Layer 0  Scaffold + CI         make ci passes on empty codebase          DONE
Layer 1  Platform Schemas      Pydantic contracts for every boundary      DONE
Layer 2  Platform Utilities    config, logger, metrics, llm, retrieval, parsers, storage, testing/factories
Layer 3  DYNAFIT Module        5-phase LangGraph pipeline, calls platform/ only
Layer 4  API + Workers + UI    FastAPI, Celery, React — dispatchers only
```

**One component per session.** Confirm exactly what is being built before writing code.

---

## Dependency Rule

```
api/ → modules/ → agents/ → platform/
```

Never sideways (between modules). Never downward (platform cannot import agents).
CI rejects violations on every PR via `make validate-contracts`.

---

## Where to Find What

| Need | Read |
|------|------|
| Hard rules for Claude (what to build, how) | `docs/rules.md` |
| Layer diagram, team ownership, failure modes | `docs/architecture.md` |
| Mistakes made and the rules they produced | `docs/lessons.md` |
| DYNAFIT 5-phase algorithms + prompts | `docs/specs/dynafit.md` (Layer 3 only) |
| API endpoints, WebSocket, DB schema, React | `docs/specs/api.md` (Layer 4 only) |
| TDD patterns, Docker setup, golden fixtures | `docs/specs/tdd.md` |

**Read `docs/rules.md` before writing any code in this project.**

---

## Current State

- Layer 0: complete
- Layer 1: complete — all schemas in `platform/schemas/`
- Layer 2: not started — build one component at a time starting with `platform/config/settings.py`
