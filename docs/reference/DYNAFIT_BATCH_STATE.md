# Dynafit Batch State — Issues & Refactor Plan

**Status:** Analysis complete. Implementation planned but not yet started.

---

## Problem Summary (4 Critical Issues)

| Issue | Severity | Impact |
|-------|----------|--------|
| In-memory `_batches` dict | CRITICAL | Process restart = data loss; no horizontal scaling |
| No batch schema | HIGH | No type safety, no IDE support |
| Unclear field ownership | HIGH | Race conditions; precedence rules vague |
| No PostgreSQL persistence | CRITICAL | No audit trail; no durability; compliance failure |

---

## Issue 1: In-Memory `_batches` Dict

**Location:** `api/routes/dynafit.py:62`

Global `_batches: dict[str, dict[str, Any]] = {}` is the single source of truth.

**Consequences:**
- Process restart → all in-memory state lost
- Horizontal scaling breaks — second API instance invisible to first server's dict
- No durability: recent batches not yet in Redis when server crashes
- Precedence unclear: recovery gymnastics when both in-memory + Redis have partial state

---

## Issue 2: Vague Definitions

**Problem A — No Batch Schema:** Batch is `dict[str, Any]`, no Pydantic model. No IDE autocomplete, no validation, no migrations.

**Problem B — Field Ownership:** `_sync_from_redis()` merges two sources with unclear precedence. Scalar fields always refreshed from Redis; list fields only loaded if empty. **Race condition:** Redis update ignored if in-memory already has data.

**Problem C — Summary Mismatch:** Code creates inline dict `{total, fit, partial_fit, gap}`. API model `BatchSummary` adds `by_module`. **Which schema is real?**

**Problem D — Results vs Journey:** Results data lives in two places: full `journey` history + flat `results` table. `_derive_results_from_journey()` regenerates on every access.

---

## Issue 3: Missing PostgreSQL Persistence

**Not stored:** Batches metadata, batch results, review items, summaries, lifecycle events.

**Consequences:**
- Redis failure = total data loss
- No cross-instance visibility
- No compliance audit trail
- Cannot query "all batches Q1 2026 for country=IN"
- Violates dependency rule (batch state outside `platform/storage/`)

---

## Issue 4: Eager Logic Building

**Results derived on every access** → O(n) reconstruction per GET /results call, no caching.

**Config contaminated:** `_upload_meta` mixed into user config; Celery must know internal schema; tight coupling.

**Review overrides vague:** When called? No validation that review_items match original atom_ids? No audit trail.

---

## Refactor Plan: Single Source of Truth

**Architecture:**
```
BEFORE: API Server A (_batches) → Redis → Data loss
AFTER:  API Servers → PostgreSQL (source of truth)
                    → Redis (transient progress only)
```

### Implementation Summary (9 Phases)

1. **Create `BatchRecord` dataclass + PostgreSQL table** with schema: batch_id, upload_id, product_id, country, wave, status, created_at, completed_at, report_path, summary (JSONB)

2. **Add PostgreSQL methods:** `save_batch()`, `get_batch_by_id()`, `update_batch_status()`, `update_batch_on_complete()`, `list_batches()`

3. **Create Batch Pydantic models** ensuring `BatchSummary` matches DB schema

4. **Remove in-memory `_batches` dict** — refactor `_get_batch()` to query PostgreSQL instead

5. **Rethink Redis role** — store only transient state: phases progress, live classifications, HITL decisions, journey. PostgreSQL = authoritative for lifecycle.

6. **Fix `run_pipeline()` ownership** — single write to DB instead of split memory + Redis write

7. **Fix results representation** — remove separate `results` blob; derive on-demand from `journey`

8. **Add `review_items` PostgreSQL table** with batch_id, atom_id, decision, reviewer, reviewed, timestamps. Write decisions to DB immediately.

9. **Update Celery worker** to write final state to PostgreSQL batches table

---

## Key Implementation Notes

**Field Ownership (post-refactor):**
- **PostgreSQL (durable):** batch_id, status, created_at, completed_at, report_path, summary
- **Redis (ephemeral):** phases progress, live classifications, HITL decisions, journey trace
- **Result:** Single source of truth; Redis loss ≠ batch loss

**Testing Impact:**
- Integration tests require real PostgreSQL (not mocks)
- WebSocket progress tests still use Redis
- No public API contract changes

**Safety:** Refactor isolated to dynafit module. No other modules create batches.

---

## References

- Implementation order: create table → remove dict → update run_pipeline → fix Redis role → add review_items table → wire Celery
- Risk: grep `modules/dynafit/` and `agents/` before merge to confirm no batch state imports
