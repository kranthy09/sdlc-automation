# Enterprise AI Platform

Enterprise AI agent platform for automating ERP implementation workflows.
**REQFIT** (D365 F&O Requirement Fitment Engine) is Module 1.

---

## The Invariant That Must Never Break

> A new product team onboards by adding files to `knowledge_bases/` and `modules/`.
> They make **zero changes** to `platform/`, `agents/`, or `api/`.

If product #2 requires touching `platform/`, the abstraction is wrong. Fix it first.

---

## Dependency Rule

```
api/ -> modules/ -> agents/ -> platform/
```

Never sideways (between modules). Never downward (platform cannot import agents).
CI rejects violations on every PR via `make validate-contracts`.

---

## Where to Find What

| Need                                                  | Read                       |
| ----------------------------------------------------- | -------------------------- |
| Architecture, import rules, code standards, lessons   | `docs/specs/rules.md`      |
| REQFIT 5-phase algorithms, prompts, library rationale | `docs/specs/dynafit.md`    |
| API endpoints, WebSocket, DB schema, React UI         | `docs/specs/api.md`        |
| MVP guardrails + post-MVP roadmap                     | `docs/specs/guardrails.md` |
| Testing philosophy, golden fixtures, build order      | `docs/specs/tdd.md`        |
| Architecture diagrams (SVG)                           | `docs/architecturalflows/` |

**Read `docs/specs/rules.md` before writing any code in this project.**

---

## Current State

All layers complete:

- Layer 0: Scaffold + CI
- Layer 1: Platform Schemas (`platform/schemas/`)
- Layer 2: Platform Utilities (13 components + guardrail utilities)
- Layer 3: REQFIT Module (5 phases in `modules/dynafit/`)
- Layer 4: API + Workers + UI (FastAPI, Celery, WebSocket, React)

**One component per session.** Confirm exactly what is being built before writing code.
