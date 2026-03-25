# Enterprise AI Platform

Enterprise AI agent platform for automating ERP implementation workflows.
**REQFIT** (D365 F&O Requirement Fitment Engine) is Module 1. All 4 layers complete.

## Invariant

New product teams add files to `knowledge_bases/` and `modules/` only — zero changes to `platform/`, `agents/`, or `api/`.

## Dependency Rule

```
api/ -> modules/ -> agents/ -> platform/
```

Never sideways. Never downward. CI enforces via `make validate-contracts`.

## Specs (read on demand — only when the task needs it)

| Task needs                              | Read                       |
| --------------------------------------- | -------------------------- |
| Import rules, coding standards          | `docs/specs/rules.md`      |
| REQFIT phases, prompts, library choices | `docs/specs/dynafit.md`    |
| API, WebSocket, DB schema, React UI     | `docs/specs/api.md`        |
| Guardrails, HITL design                 | `docs/specs/guardrails.md` |

**One component per session.** Confirm exactly what is being built before writing code.
