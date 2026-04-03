---
name: REQFIT Phase Alignment & Flow Verification Report
description: Complete verification of 5-phase pipeline architecture, data flow, guardrails, and event sequencing (2026-04-03)
type: project
---

# REQFIT 5-Phase Pipeline — Alignment & Flow Verification Report

**Date:** 2026-04-03  
**Scope:** Verify all 5 phases are correctly aligned, data flows correctly, guardrails are implemented, and events are published  
**Status:** ✅ **MOSTLY ALIGNED** with 3 minor issues identified

---

## Executive Summary

The REQFIT 5-phase pipeline is **fundamentally sound** and correctly architected. All phase nodes read the correct state fields, write the correct outputs, and follow the linear dependency chain. LangGraph checkpointing is properly configured, HITL interrupt points are set up, and the API layer correctly dispatches tasks.

**Three minor issues found:**
1. **HIGH severity:** G10-lite scope mismatch — Phase 5 implements 5 sanity checks not defined in `guardrails.py`
2. **MEDIUM severity:** Missing `publish_phase_start()` event when no items are flagged in Phase 5
3. **LOW severity:** Phase 5 doesn't publish `publish_step_progress()` events (optional enhancement)

All issues are **non-blocking** and do not prevent pipeline execution. Recommendations provided.

---

## 1. PHASE NODE ARCHITECTURE ✅ CORRECT

### Graph Structure

**File:** `modules/dynafit/graph.py` (lines 48-88)

The LangGraph is correctly configured as a linear pipeline:

```
ingestion → retrieve → match → classify → validate → END
   (P1)      (P2)      (P3)    (P4)       (P5)
```

**Interrupt points configured (line 83):**
```python
interrupt_before=["retrieve", "match", "classify", "validate"]
```

This allows:
- **Gate 1** between Phase 1 and Phase 2 (retrieve)
- **Gate 2** between Phase 2 and Phase 3 (match)
- **Gate 3** between Phase 3 and Phase 4 (classify)
- **Gate 4** between Phase 4 and Phase 5 (validate)
- **HITL** within Phase 5 via `interrupt()` call

All entry points exist: `set_entry_point("ingest")` at line 78 ✓

---

### State Contract Compliance

**File:** `modules/dynafit/state.py` (lines 32-80)

All phase inputs/outputs correctly defined in `DynafitState` TypedDict:

| Phase | Input Fields | Output Fields | Status |
|-------|--------------|---------------|--------|
| **1 (Ingestion)** | `upload`, `batch_id` | `atoms`, `validated_atoms`, `flagged_atoms`, `enriched_chunks`, `artifact_store_batch_path`, `pii_redaction_map` | ✅ |
| **2 (Retrieval)** | `validated_atoms`, `batch_id`, `upload` | `retrieval_contexts` | ✅ |
| **3 (Matching)** | `retrieval_contexts`, `batch_id` | `match_results` | ✅ |
| **4 (Classification)** | `match_results`, `validated_atoms`, `retrieval_contexts`, `batch_id` | `classifications` | ✅ |
| **5 (Validation)** | `classifications`, `match_results`, `batch_id`, `pii_redaction_map` | `validated_batch` | ✅ |

**Cross-cutting fields:**
- `errors: Annotated[list[str], operator.add]` ✓ (LangGraph reducer merges lists across phases)
- `config_overrides: NotRequired[dict[str, Any]]` ✓ (used by Phase 4-5)

---

### Phase Node Implementations

#### Phase 1 — Ingestion Node

**File:** `modules/dynafit/nodes/ingestion.py` (lines 668-675)

```python
def ingestion_node(state: DynafitState) -> dict[str, Any]:
    """Phase 1 LangGraph node — delegates to cached IngestionNode instance."""
```

**Entry signature:** Reads `state["upload"]`, `state["batch_id"]`  
**Return signature (lines 525-537):**
```python
return {
    "atoms": classified,           # RequirementAtom[]
    "validated_atoms": validated,   # ValidatedAtom[]
    "flagged_atoms": flagged,       # FlaggedAtom[]
    "enriched_chunks": chunks_serialized,  # Optional
    "artifact_store_batch_path": store.batch_path,  # Optional
    "pii_redaction_map": combined_redaction_map,    # Optional
    "errors": [reason],  # Only if early rejection
}
```

**Status:** ✅ All outputs correctly aligned with state contract

---

#### Phase 2 — Retrieval Node

**File:** `modules/dynafit/nodes/retrieval.py` (lines 631-642)

```python
async def retrieval_node(state: DynafitState) -> dict[str, Any]:
    """Phase 2 LangGraph node — async node for concurrent retrieval."""
```

**Async status:** ✅ Correctly async (awaits RRF fusion, embedding, reranking)  
**Entry signature:** Reads `state["validated_atoms"]`, `state["batch_id"]`, `state["upload"].product_id`  
**Return signature (line 362):**
```python
return {"retrieval_contexts": contexts}  # AssembledContext[]
```

**Status:** ✅ Output correctly aligned with state contract

---

#### Phase 3 — Matching Node

**File:** `modules/dynafit/nodes/matching.py` (lines 407-435)

```python
def matching_node(state: DynafitState) -> dict[str, Any]:
    """Phase 3 LangGraph node — delegates to cached MatchingNode instance."""
```

**Entry signature:** Reads `state["retrieval_contexts"]`, `state["batch_id"]`, `state["upload"].product_id`  
**Return signature (line 272):**
```python
return {"match_results": results}  # MatchResult[]
```

**Status:** ✅ Output correctly aligned with state contract

---

#### Phase 4 — Classification Node

**File:** `modules/dynafit/nodes/classification.py` (lines 684-701)

```python
def classification_node(state: DynafitState) -> dict[str, Any]:
    """Phase 4 LangGraph node — delegates to cached ClassificationNode instance."""
```

**Entry signature:** Reads `state["match_results"]`, `state["validated_atoms"]`, `state["retrieval_contexts"]`, `state["batch_id"]`, `state["upload"].product_id`, `state.get("config_overrides")`  
**Return signature (line 341):**
```python
return {"classifications": classifications}  # ClassificationResult[]
```

**Status:** ✅ Output correctly aligned with state contract

---

#### Phase 5 — Validation Node

**File:** `modules/dynafit/nodes/phase5_validation.py` (lines 483-489)

```python
def validation_node(state: DynafitState) -> dict[str, Any]:
    """Phase 5 LangGraph node — delegates to cached ValidationNode instance."""
```

**Entry signature:** Reads `state["classifications"]`, `state["match_results"]`, `state["batch_id"]`, `state.get("config_overrides")`, `state.get("pii_redaction_map")`, `state["upload"]`  
**Return signature (line 273-274):**
```python
return {"validated_batch": final_batch}  # ValidatedFitmentBatch | None
```

**Status:** ✅ Output correctly aligned with state contract

---

## 2. GUARDRAILS IMPLEMENTATION VERIFICATION

### Phase 1 Guardrails

| Guardrail | Function | File:Line | Status |
|-----------|----------|-----------|--------|
| **G1-lite** | File validation (size, format) | `ingestion.py:354-357` | ✅ Implemented, called |
| **G3-lite** | Injection scanning (prompt injection) | `ingestion.py:414` | ✅ Implemented, called |
| **G2** | PII redaction (Presidio + regex) | `ingestion.py:433-449` | ✅ Implemented, called |

All Phase 1 guardrails correctly invoked before atoms are produced.

### Phase 4 Guardrails

| Guardrail | Function | File:Line | Status |
|-----------|----------|-----------|--------|
| **G8** | Prompt firewall (Jinja2 autoescape, StrictUndefined) | `classification.py:535-541` | ✅ Implemented via `render_prompt()` |
| **G9** | Schema validation (Pydantic strict mode) | `classification.py:542-547` | ✅ Enforced by LLMClient |
| **G11** | Response PII scanning (scan LLM output) | `classification.py:382` + `_scan_for_response_pii()` | ✅ Implemented, called |

All Phase 4 guardrails correctly enforced.

### Phase 5 Guardrails — ⚠️ ISSUE FOUND

**File:** `modules/dynafit/nodes/phase5_validation.py` (lines 277-356)

**G10-lite definition (in `modules/dynafit/guardrails.py`, lines 35-87):**

The guardrails module defines 3 sanity checks:
1. `high_confidence_gap`: confidence ≥ 0.85 AND classification = GAP
2. `low_score_fit`: top_composite_score < 0.60 AND classification = FIT
3. `llm_schema_retry_exhausted`: classification = REVIEW_REQUIRED

**Actual sanity checks in Phase 5 (lines 296-354):**

Phase 5's `_check_flags()` method calls `run_sanity_check()` at line 299, but then adds **5 additional checks inline** at lines 305-354:

1. ✅ `high_confidence_gap` — via `run_sanity_check()`
2. ✅ `low_score_fit` — via `run_sanity_check()`
3. ✅ `llm_schema_retry_exhausted` — via `run_sanity_check()`
4. ❌ **`low_confidence`** (lines 305-317) — **NOT in guardrails.py**
5. ❌ **`gap_review`** (lines 319-322) — **NOT in guardrails.py**
6. ❌ **`phase3_anomaly`** (lines 324-331) — **NOT in guardrails.py**
7. ❌ **`response_pii_leak`** (lines 333-339) — **This is G11, not G10**
8. ❌ **`partial_fit_no_config`** (lines 345-354) — **NOT in guardrails.py**

**Status:** ❌ **SCOPE MISMATCH** — 5 checks implemented in Phase 5 but not in guardrails.py

**Severity:** HIGH — Makes it unclear what "G10-lite" actually includes. Future maintainers cannot rely on the spec.

**Impact:** Non-blocking. All checks are correctly implemented and necessary for HITL. Just poorly documented.

---

## 3. EVENT PUBLISHING & PROGRESS TRACKING

### Phase 1 Events

**File:** `modules/dynafit/nodes/ingestion.py`

| Event | Line | Condition | Status |
|-------|------|-----------|--------|
| `publish_phase_start` | 347 | Always at start | ✅ |
| `publish_step_progress` | 168, 404, 475, 490 | Per sub-step | ✅ |
| `publish_phase_complete` | 515 | Always at end | ✅ |

**Status:** ✅ Correct event sequence

### Phase 2 Events

**File:** `modules/dynafit/nodes/retrieval.py`

| Event | Line | Condition | Status |
|-------|------|-----------|--------|
| `publish_phase_start` | 319 | Always at start | ✅ |
| `publish_step_progress` | 390, 414, 440, 448 | Per sub-step | ✅ |
| `publish_phase_complete` | 353 | Always at end | ✅ |

**Status:** ✅ Correct event sequence

### Phase 3 Events

**File:** `modules/dynafit/nodes/matching.py`

| Event | Line | Condition | Status |
|-------|------|-----------|--------|
| `publish_phase_start` | 178 | Always at start | ✅ |
| `publish_step_progress` | 227, 242 | Per sub-step | ✅ |
| `publish_phase_complete` | 263 | Always at end | ✅ |

**Status:** ✅ Correct event sequence

### Phase 4 Events

**File:** `modules/dynafit/nodes/classification.py`

| Event | Line | Condition | Status |
|-------|------|-----------|--------|
| `publish_phase_start` | 246 | Always at start | ✅ |
| `publish_step_progress` | 307 | Per LLM call batch | ✅ |
| `publish_phase_complete` | 332 | Always at end | ✅ |

**Status:** ✅ Correct event sequence

### Phase 5 Events — ⚠️ ISSUE FOUND

**File:** `modules/dynafit/nodes/phase5_validation.py` (lines 155-274)

| Event | Line | Condition | Status |
|-------|------|-----------|--------|
| `publish_phase_start` | 201-205 | **ONLY if flagged items exist** | ❌ Conditional |
| `publish_step_progress` | (none) | Never published | ⚠️ Missing |
| `publish_phase_complete` | 250 | Always at end | ✅ |

**Issue 1 — Missing phase_start (MEDIUM severity):**

```python
if flagged:
    publish_phase_start(
        batch_id,
        phase=5,
        phase_name="human_review",
    )
```

**Problem:** If no items are flagged, `publish_phase_start` is never called. This breaks the pattern where every phase starts with `publish_phase_start()`.

**Why it matters:** UI/logging expects phase_start → [progress events] → phase_complete. When phase_start is missing, the phase appears to start without announcement.

**Issue 2 — No step_progress events (LOW severity):**

Phases 1-4 all call `publish_step_progress()` for each sub-step. Phase 5 has two distinct passes (sanity gate + HITL, then merge/build/output) but publishes no progress events.

**Why it matters:** UI cannot show progress within Phase 5. For long-running validation, this is poor UX.

---

## 4. ERROR HANDLING & ACCUMULATION

**File:** `modules/dynafit/state.py` (line 38)

```python
errors: Annotated[list[str], operator.add]  # LangGraph reducer merges lists
```

**Error accumulation verified:**

- Phase 1 initializes: `"errors": [reason]` at line 109 (early rejection)
- Phase 1 returns: `"errors": extra_errors` at line 529
- All phases: No phase 2-5 emit errors (correct, since they have no early rejections)
- LangGraph: Automatically merges error lists via `operator.add` reducer

**Logging verified:**
- All 5 phases log via `log.info()`, `log.warning()`, `log.debug()` ✅
- Error messages are structured (context keys: batch_id, phase, etc.) ✅
- All phases use `get_logger(__name__)` from platform/observability ✅

**Status:** ✅ Correct error handling and logging

---

## 5. ASYNC/AWAIT CORRECTNESS

### Async Phases

**Phase 2 (Retrieval) is correctly async:**

- **Node function (line 631):** `async def retrieval_node(state: DynafitState)`
- **Class method (line 313):** `async def __call__(self, state: DynafitState)`
- **Awaits (line 342):** `contexts = await self._run(atoms, config, batch_id=batch_id)`
- **Parallel operations:** Uses `asyncio.gather()` for concurrent retrieval from 3 sources ✅

### Non-Async Phases

All other phases are correctly synchronous:
- Phase 1: `def ingestion_node()` ✅
- Phase 3: `def matching_node()` ✅
- Phase 4: `def classification_node()` ✅
- Phase 5: `def validation_node()` ✅

### LangGraph Handling

**File:** `modules/dynafit/graph.py` (line 81)

```python
compiled = graph.compile(checkpointer=checkpointer, ...)
```

LangGraph natively handles mixed sync/async nodes. The async `retrieval_node` is invoked with `ainvoke()` internally by LangGraph. ✅

---

## 6. DATA FLOW VERIFICATION

### Flow from Phase 1 → Phase 2

**Phase 1 output:** `validated_atoms` (list[ValidatedAtom])  
**Phase 2 input:** `state.get("validated_atoms", [])` (retrieval.py:315)  
**Status:** ✅ Correct

### Flow from Phase 2 → Phase 3

**Phase 2 output:** `retrieval_contexts` (list[AssembledContext])  
**Phase 3 input:** `state.get("retrieval_contexts", [])` (matching.py:195)  
**Status:** ✅ Correct

### Flow from Phase 3 → Phase 4

**Phase 3 output:** `match_results` (list[MatchResult])  
**Phase 4 input:** `state.get("match_results", [])` (classification.py:235)  
**Status:** ✅ Correct

### Flow from Phase 4 → Phase 5

**Phase 4 output:** `classifications` (list[ClassificationResult])  
**Phase 5 input:** `state.get("classifications", [])` (phase5_validation.py:160)  
**Status:** ✅ Correct

### Cross-Phase Dependencies

**Phase 1 → Phase 5:**
- **Phase 1 output:** `pii_redaction_map`
- **Phase 5 input:** `state.get("pii_redaction_map")` (line 230)
- **Usage:** PII restoration in CSV output (line 428-433)
- **Status:** ✅ Correct

**Phase 2 → Phase 4:**
- **Phase 2 output:** `retrieval_contexts` (contains prior_fitments)
- **Phase 4 input:** `state.get("retrieval_contexts", [])` (line 292, used for prompt context)
- **Status:** ✅ Correct

**Phase 3 → Phase 5:**
- **Phase 3 output:** `match_results` (contains composite_score, anomaly_flags)
- **Phase 5 input:** `state.get("match_results", [])` (line 160, used for sanity checks)
- **Status:** ✅ Correct

---

## 7. API & WORKER LAYER ALIGNMENT

### Task Dispatch

**File:** `api/routes/dynafit.py` (lines 74-88)

- Validates upload → persists metadata to PostgreSQL ✅
- Enqueues Celery task: `run_dynafit_pipeline.delay()` ✅

### Worker Task

**File:** `api/workers/tasks.py` (lines 628-816)

**First-run path (lines 754-800):**
1. Reconstruct `RawUpload` from metadata
2. Create graph with `AsyncPostgresSaver` (PostgreSQL checkpointer)
3. `graph.ainvoke()` Phase 1 with initial state
4. Extract gate 1 data from state
5. Publish gate event
6. Return (pauses before Phase 2)

**Gate proceed path (lines 508-614):**
- Resume from checkpoint
- Run next phase
- Extract gate data
- Publish gate event
- Repeat until Phase 5

**HITL resume path (lines 491-505):**
- `graph.ainvoke(Command(resume=overrides), ...)`
- Resume Phase 5 with human decisions
- Finish with `_finish_complete()`

**Status:** ✅ Correct dispatcher architecture

---

## 8. CHECKPOINT & HITL CONFIGURATION

### Checkpointer Setup

**File:** `api/workers/tasks.py` (lines 761-767)

```python
async with AsyncPostgresSaver.from_conn_string(
    POSTGRES_CHECKPOINT_URL, serde=JsonPlusSerializer()
) as checkpointer:
    await checkpointer.setup()
    graph = build_dynafit_graph(checkpointer=checkpointer)
```

**Status:** ✅ Correctly configured with JSON serializer

### Interrupt Points

**File:** `modules/dynafit/graph.py` (line 83)

```python
interrupt_before=["retrieve", "match", "classify", "validate"]
```

- Gate 1: Between Phase 1 and 2 ✅
- Gate 2: Between Phase 2 and 3 ✅
- Gate 3: Between Phase 3 and 4 ✅
- Gate 4: Between Phase 4 and 5 ✅

### HITL Checkpoint

**File:** `modules/dynafit/nodes/phase5_validation.py` (lines 200-223)

```python
raw = interrupt({
    "batch_id": batch_id,
    "flagged_count": len(flagged),
    "flagged_atom_ids": [...],
    "flagged_reasons": {...},
})
```

**Status:** ✅ Correctly calls LangGraph interrupt() with payload

---

## 9. RECENT BUG FIXES VERIFICATION

### Artifact Storage Fix

**Issue:** Swapped arguments in `store.store_all()` prevented artifact storage

**Fix applied:** Changed `store.store_all(docling_doc, elements)` → `store.store_all(elements, extractor)`

**Files modified:**
1. `modules/dynafit/nodes/ingestion.py:577` ✅
2. `platform/ingestion/artifact_store.py:53` (docstring) ✅
3. `tests/integration/test_ingestion_journey.py:95` ✅

**Verification:** All 3 locations updated ✅

### RRF Fusion Fix

**Issue:** Capability IDs collided with doc IDs, causing capabilities to be overwritten

**Fix applied:** Added composite keys with source prefixes: `cap:`, `doc:`, `prior:`

**File:** `modules/dynafit/nodes/rrf_fusion.py`

**Status:** ✅ Implemented

### Chunker Oversizing Fix

**Issue:** Text files producing only 1 requirement due to oversized element not being split

**Fix applied:** Added `_split_oversized_element()` method to split at paragraph boundaries

**File:** `platform/ingestion/chunker.py:148-155`

**Status:** ✅ Implemented

### Module Filter Fallback

**Issue:** Wrong module assignment → empty capability search

**Fix applied:** Added fallback to global search when module-filtered search returns nothing

**File:** `modules/dynafit/nodes/retrieval.py:524-525`

**Status:** ✅ Implemented

---

## ISSUES SUMMARY

| ID | Severity | Component | Issue | Location | Fix |
|----|----------|-----------|-------|----------|-----|
| **I1** | HIGH | Phase 5 Guardrails | G10-lite scope mismatch: 5 sanity checks implemented but not defined in guardrails.py | `phase5_validation.py:277-356` | Integrate checks into `guardrails.py::run_sanity_check()` or document separately |
| **I2** | MEDIUM | Phase 5 Events | Missing `publish_phase_start()` when no items flagged | `phase5_validation.py:201-205` | Always publish phase_start, even when flagged=empty |
| **I3** | LOW | Phase 5 Events | No `publish_step_progress()` events published | `phase5_validation.py:155-274` | (Optional) Add step progress for sanity gate, HITL wait, merge/build steps |

---

## RECOMMENDATIONS

### Critical (Address I1 — G10-lite scope)

1. **Integrate Phase 5 checks into guardrails.py:**

   Option A: Extend `run_sanity_check()` to include all 8 checks:
   ```python
   def run_sanity_check(result: ClassificationResult, match: MatchResult | None, 
                        config: ProductConfig) -> list[str]:
       """Return list of flag names if any G10-lite sanity checks fail."""
       # Include current 3 checks + the 5 additional Phase 5 checks
   ```

   Option B: Create separate `run_phase5_validation()` function and call explicitly:
   ```python
   g10_flags = run_sanity_check(result, match, config)
   phase5_flags = run_phase5_validation(result, match, config)
   flags = g10_flags + phase5_flags
   ```

2. **Update specs:** Clarify in `docs/specs/dynafit_phases.md` §Phase 5 whether these 5 checks are G10-lite or Phase 5-specific.

3. **Update docstring:** Add comment in `phase5_validation.py::_check_flags()` explaining which checks come from guardrails.py vs. which are Phase 5-specific.

### Important (Address I2 — Missing phase_start event)

1. **Move `publish_phase_start()` outside the `if flagged:` block:**

   **Current (lines 200-205):**
   ```python
   if flagged:
       publish_phase_start(...)
   ```

   **Proposed:**
   ```python
   publish_phase_start(batch_id, phase=5, phase_name="Validation")  # Always
   
   if flagged:
       # Publish human_review event, then interrupt
       publish_phase_start(batch_id, phase=5, phase_name="human_review")
       ...
   ```

   Or use a single phase_name parameter that indicates the sub-phase (e.g., "Validation (Auto)" vs "Validation (HITL)").

### Optional (Address I3 — Add step progress)

1. **Add progress events for multi-pass structure:**
   ```python
   publish_step_progress(batch_id, phase=5, step="sanity_gate", completed=1, total=3)
   # ... sanity checks ...
   
   if flagged:
       publish_step_progress(batch_id, phase=5, step="hitl_wait", completed=2, total=3)
       # ... interrupt ...
   
   publish_step_progress(batch_id, phase=5, step="merge_and_output", completed=3, total=3)
   # ... merge, build, output ...
   ```

---

## CONCLUSION

The REQFIT 5-phase pipeline is **well-architected and correctly implemented**. All phases flow correctly, state contracts are honored, and the LangGraph execution model is properly configured. The 3 issues found are **documentation/polish** issues, not functionality issues.

**Recommendation:** Address I1 (guardrails scope) before the next major release to avoid confusion. I2 and I3 are enhancements that can be deferred.

**Pipeline status: READY FOR PRODUCTION** ✅
