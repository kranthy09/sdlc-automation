# SDLC Automation Platform — Codebase Review & Optimization Plan

> **Purpose:** Deep technical review of the sdlc-automation codebase, identifying business logic bottlenecks, UX gaps in the consultant flow through Module 1 (REQFIT), and providing a step-by-step implementation plan executable via Claude Code.

---

## Part 1: Architecture Review Summary

### What's Working Well

The architecture is genuinely enterprise-grade. The 4-layer dependency rule (`api/ → modules/ → agents/ → platform/`) with CI enforcement is a strong invariant that prevents coupling decay. The LangGraph backbone with PostgreSQL checkpointing gives crash recovery and HITL support natively. The separation of concerns is clean — every node reads from `DynafitState`, transforms, and returns a partial dict. The Redis pub/sub → WebSocket → React progress pipeline is the right pattern for long-running AI workloads. Pydantic v2 schemas at every boundary eliminate an entire class of runtime errors.

### What Needs Improvement

The problems cluster around three themes: **consultant experience visibility**, **long-running call optimization**, and **frontend reload/state loss**. Below is the detailed analysis.

---

## Part 2: Business Logic Review — Critical Findings

### Finding 1: Consultant Cannot See Output Being Generated in Real-Time

**Problem:** The pipeline runs phases 1–4 as a monolithic Celery task. During Phase 4 (Classification), the LLM processes 50+ requirements sequentially (80 LLM calls). The consultant sees a progress bar moving, but cannot see individual classification results until the entire Phase 4 completes and the batch transitions to Phase 5.

**Root Cause in Code:**

```
# modules/dynafit/nodes/classification.py
# Currently: processes ALL atoms, publishes ONE classification event per atom
# BUT the frontend only renders these in the LiveClassTable AFTER they arrive via WebSocket

# api/workers/tasks.py
# The Celery task calls graph.ainvoke() which blocks until phases 1-4 complete
# Only THEN does _finish_complete() or _finish_hitl() write results to Redis
```

The `classification` WebSocket messages ARE emitted per-atom during Phase 4 (the spec confirms this), but the **results data** (the full journey, evidence, rationale) is only assembled AFTER the entire pipeline completes in `presentation.py → build_complete_data()`. So the consultant sees "REQ-AP-041 → FIT 0.94" in the live table but **cannot drill into WHY** until the whole batch finishes.

**Impact:** For a 50-requirement batch taking ~120 seconds, the consultant stares at a progress bar for 2 minutes with no ability to start reviewing early results.

### Finding 2: Results Page Journey Data Loaded On-Demand Per Row (N+1 Problem)

**Problem:** In `ResultRow.tsx`, each row expansion triggers a separate `GET /journey?atom_id=X` call:

```typescript
// ui/src/components/results/ResultRow.tsx
const { data: journeyData } = useJourney(
  batchId,
  open ? result.atom_id : undefined,
);
```

For a consultant reviewing 50 results and expanding 20 of them, that's 20 sequential HTTP round-trips to FastAPI, each of which calls `_sync_from_redis()` → parses the full journey JSON → filters to one atom.

**Root Cause in Code:**

```python
# api/routes/dynafit.py → get_journey()
journey: list[dict[str, Any]] = batch.get("journey", [])
if atom_id:
    journey = [j for j in journey if j["atom_id"] == atom_id]
```

The backend loads the ENTIRE journey array from Redis on every single call, then filters. The journey data for 50 atoms is ~200KB of JSON being deserialized repeatedly.

### Finding 3: In-Memory Batch Store Causes Data Loss on Restart

**Problem:** The route layer uses a module-level dict `_batches` as the primary store:

```python
# api/routes/dynafit.py
_batches: dict[str, dict[str, Any]] = {}
```

While `_sync_from_redis()` hydrates from Redis, the initial `POST /run` creates the batch only in `_batches`. If the FastAPI process restarts between "run" and "complete", the batch is lost. The `_get_batch()` function raises 404 because the batch was never persisted.

### Finding 4: Phase 4 Classification Runs Sequentially — No Parallelism

**Problem:** From the spec, Phase 4 makes 80 LLM calls for 50 requirements (30 FAST_TRACK × 1 + 15 DEEP_REASON × 3 + 5 GAP_CONFIRM × 1). These are processed sequentially in the classification node, which is the single biggest latency bottleneck.

**Why it matters:** LLM calls average ~1.5s each. 80 sequential calls = ~120s. With `asyncio.gather()` on batches of 10, this drops to ~12s (10x improvement).

### Finding 5: Redis Hash Duplication — Journey Data Stored Twice

**Problem:** When the pipeline completes, `_finish_complete()` writes both `results` AND `journey` as separate JSON blobs to the same Redis hash. The journey contains all the data that's also in results (classification, confidence, rationale) plus the full 5-phase trace. For 50 atoms, this duplicates ~100KB.

### Finding 6: WebSocket Reconnect Doesn't Restore Phase History

**Problem:** The `useProgress` hook reconnects on WebSocket drop and invalidates TanStack Query cache, but the Zustand `progressStore` only accumulates from live messages. If the consultant refreshes the page mid-Phase 3, they lose all Phase 1 and Phase 2 completion cards — they only see Phase 3 onwards.

**Root Cause:** There's no REST endpoint to fetch "current pipeline state" (which phases completed, their stats). The `GET /results` endpoint only works after completion. The progress state exists only in transient WebSocket messages.

---

## Part 3: Consultant Flow Through Module 1 — Improvement Design

### Current Flow (What the Consultant Experiences)

```
Upload → Wait 2min (progress bar) → See all results at once → Expand rows one-by-one → Review flagged items → Done
```

### Target Flow (What the Consultant Should Experience)

```
Upload → See Phase 1 parsing live → See Phase 2 retrieval live →
See each classification appear one-by-one with full evidence →
Start reviewing HIGH-CONFIDENCE results immediately while remaining items still process →
Review flagged items → Done
```

The key insight: **classifications should be reviewable the moment they appear, not after the entire batch completes.**

---

## Part 4: Step-by-Step Implementation Plan

Each step below is a self-contained change. Steps are ordered by impact (highest first) and dependency (prerequisites first). Each step includes the exact files to modify, what to change, and why — optimized for Claude Code execution.

---

### Step 1: Add REST Endpoint for Pipeline Progress State

**Goal:** Let the frontend recover full progress state on page refresh.

**Files to modify:**

- `api/routes/dynafit.py` — add endpoint
- `platform/storage/redis_pub.py` — add reader method
- `ui/src/api/dynafit.ts` — add API function
- `ui/src/hooks/useProgress.ts` — call on mount

**Changes:**

```python
# api/routes/dynafit.py — ADD new endpoint

@router.get("/d365_fo/dynafit/{batch_id}/progress")
def get_progress(batch_id: str) -> dict[str, Any]:
    """Return current pipeline progress state from Redis.

    Used by frontend on mount/reconnect to restore phase history
    without relying on transient WebSocket messages.
    """
    batch = _get_batch(batch_id)
    phases = RedisPubSub.read_phase_state_sync(REDIS_URL, batch_id)
    return {
        "batch_id": batch_id,
        "status": batch.get("status", "queued"),
        "phases": phases,  # dict of phase_num → {status, phase_name, progress_pct, atoms_produced, ...}
    }
```

```python
# platform/storage/redis_pub.py — ADD static method

@staticmethod
def read_phase_state_sync(redis_url: str, batch_id: str) -> dict[str, Any]:
    """Read accumulated phase progress from Redis hash."""
    import redis as sync_redis
    r = sync_redis.from_url(redis_url)
    try:
        raw = r.hget(f"batch:{batch_id}", "phases")
        return json.loads(raw) if raw else {}
    finally:
        r.close()
```

Instruction: Donot call raw backend calls, create a modular way by using a api client pattern.

```typescript
// ui/src/api/dynafit.ts — ADD function
export async function getProgress(batchId: string): Promise<ProgressSnapshot> {
  const { data } = await api.get(`/api/v1/d365_fo/dynafit/${batchId}/progress`);
  return data;
}
```

```typescript
// ui/src/hooks/useProgress.ts — ADD initial state hydration
// Inside useEffect, BEFORE opening WebSocket:
const snapshot = await getProgress(batchId);
if (snapshot.phases) {
  // Replay phase states into Zustand store
  Object.entries(snapshot.phases).forEach(([phase, data]) => {
    if (data.status === "complete") {
      applyMessage({ type: "phase_complete", phase: Number(phase), ...data });
    } else if (data.status === "active") {
      applyMessage({ type: "phase_start", phase: Number(phase), ...data });
    }
  });
}
```

**Why this matters:** Fixes Finding 6. Consultant can refresh the page at any time without losing progress history.

**Claude Code prompt:**

```
Read api/routes/dynafit.py, platform/storage/redis_pub.py, ui/src/hooks/useProgress.ts, and ui/src/api/dynafit.ts.
Add a GET /d365_fo/dynafit/{batch_id}/progress endpoint that reads phase state from the Redis hash batch:{batch_id} key "phases".
Add a read_phase_state_sync static method to RedisPubSub.
Add getProgress() to the frontend API layer.
Modify useProgress hook to call getProgress on mount before opening the WebSocket, and replay the snapshot into the Zustand progress store.
Follow the existing patterns: routes do zero logic, platform provides the Redis abstraction, frontend types mirror backend response.
```

---

### Step 2: Stream Per-Atom Classification Results with Journey Context

**Goal:** When each classification completes in Phase 4, immediately make its full journey data available — not just the summary line.

**Files to modify:**

- `modules/dynafit/nodes/classification.py` — emit richer classification event
- `platform/schemas/events.py` — extend ClassificationEvent with journey snippet
- `ui/src/stores/progressStore.ts` — accumulate classification + journey pairs
- `ui/src/pages/ProgressPage.tsx` — show expandable evidence on live classifications

**Changes:**

```python
# modules/dynafit/nodes/classification.py
# Inside the per-atom classification loop, AFTER classifying each atom:

# Current: publishes ClassificationEvent with basic fields
# Change: also include the journey context for this atom

from modules.dynafit.presentation import build_single_atom_journey

journey_snippet = build_single_atom_journey(
    atom=atom,
    context=retrieval_contexts_by_atom.get(atom.atom_id),
    match_result=match_results_by_atom.get(atom.atom_id),
    classification=cls_result,
)

publish_classification(
    batch_id=batch_id,
    atom_id=cls_result.atom_id,
    requirement_text=cls_result.requirement_text,
    classification=str(cls_result.classification),
    confidence=cls_result.confidence,
    module=cls_result.module,
    rationale=cls_result.rationale,
    journey=journey_snippet,  # NEW: include inline journey data
)
```

```python
# modules/dynafit/presentation.py — ADD new function

def build_single_atom_journey(
    atom: ValidatedAtom | None,
    context: AssembledContext | None,
    match_result: MatchResult | None,
    classification: ClassificationResult,
) -> dict[str, Any]:
    """Build journey data for a single atom during streaming.

    This is the real-time counterpart to build_journey_data().
    Called per-atom as classifications complete, so the consultant
    can drill into evidence immediately.
    """
    # Reuse the same structure as build_journey_data but for one atom
    # (extract the per-atom logic into a shared helper)
    ...
```

**Why this matters:** Fixes Finding 1. The consultant sees each classification appear in the live table AND can immediately expand it to see the full 5-phase evidence trail — D365 capabilities matched, confidence signals, rationale — without waiting for the entire batch to complete.

**Claude Code prompt:**

```
Read modules/dynafit/presentation.py (specifically build_journey_data), modules/dynafit/nodes/classification.py, and platform/schemas/events.py.

1. Extract the per-atom journey building logic from build_journey_data() into a new function build_single_atom_journey(atom, context, match_result, classification) that returns one journey dict.
2. Refactor build_journey_data() to call build_single_atom_journey() in its loop to eliminate duplication.
3. In the classification node, after each atom is classified, call build_single_atom_journey() and include the result in the ClassificationEvent published to Redis.
4. Extend ClassificationEvent in platform/schemas/events.py to include an optional journey field.
5. In ui/src/stores/progressStore.ts, store the journey alongside each classification in the classifications array.
6. In ui/src/pages/ProgressPage.tsx LiveClassTable, make each row expandable (like ResultRow) showing the journey evidence panel.

Preserve all existing behavior — this is additive only.
```

---

### Step 3: Batch-Load Journey Data Instead of N+1

**Goal:** Eliminate the N+1 journey loading problem on the Results page.

**Files to modify:**

- `api/routes/dynafit.py` — modify `get_results` to include journey inline
- `ui/src/hooks/useResults.ts` — use inline journey data
- `ui/src/components/results/ResultRow.tsx` — use pre-loaded journey
- `ui/src/hooks/useJourney.ts` — keep as fallback only

**Changes:**

```python
# api/routes/dynafit.py — modify get_results endpoint

@router.get("/d365_fo/dynafit/{batch_id}/results")
def get_results(batch_id: str, ...) -> ResultsResponse:
    batch = _get_batch(batch_id)
    results = batch.get("results", [])
    journey_data = batch.get("journey", [])

    # Build a lookup map once
    journey_by_atom = {j["atom_id"]: j for j in journey_data}

    # Attach journey to each result in the response
    enriched = []
    for r in paginated_results:
        enriched.append({
            **r,
            "journey": journey_by_atom.get(r["atom_id"]),
        })

    return ResultsResponse(
        batch_id=batch_id,
        results=enriched,
        ...
    )
```

```typescript
// ui/src/components/results/ResultRow.tsx — use pre-loaded journey
// BEFORE:
const { data: journeyData } = useJourney(
  batchId,
  open ? result.atom_id : undefined,
);
const atomJourney = journeyData?.atoms?.[0] ?? null;

// AFTER:
const atomJourney = result.journey ?? null;
// No network call needed — journey data comes with the results response
```

**Why this matters:** Fixes Finding 2. Eliminates 20+ sequential HTTP calls when a consultant reviews results. The results page loads once with all journey data included. For the 25-item default page size, this saves ~2s of round-trip latency.

**Claude Code prompt:**

```
Read api/routes/dynafit.py (get_results endpoint), ui/src/hooks/useResults.ts, ui/src/hooks/useJourney.ts, ui/src/components/results/ResultRow.tsx, and ui/src/api/types.ts.

1. Modify get_results to attach journey data inline to each result by building a journey_by_atom lookup from the batch journey data.
2. Update the ResultsResponse type and FitmentResult TypeScript type to include an optional journey field.
3. In ResultRow.tsx, use result.journey directly instead of calling useJourney(). Keep useJourney as a fallback if journey is null.
4. Ensure the journey data is only for the current page of results (not all 50 atoms) to keep response size manageable.

This eliminates the N+1 query pattern on the results page.
```

---

### Step 4: Persist Batch State to Redis on Creation (Not Just In-Memory)

**Goal:** Prevent batch data loss on FastAPI restart.

**Files to modify:**

- `api/routes/dynafit.py` — write to Redis on batch creation

**Changes:**

```python
# api/routes/dynafit.py — in start_analysis endpoint

# CURRENT: only writes to _batches (in-memory dict)
_batches[batch_id] = { "batch_id": batch_id, "status": "queued", ... }

# ADD: also persist initial state to Redis
RedisPubSub.write_batch_state_sync(
    REDIS_URL, batch_id,
    status="queued",
    upload_id=upload_id,
    created_at=_now(),
)
```

```python
# api/routes/dynafit.py — modify _get_batch to recover from Redis

def _get_batch(batch_id: str) -> dict[str, Any]:
    batch = _batches.get(batch_id)
    if batch is None:
        # Try recovering from Redis (survives process restart)
        data = RedisPubSub.read_batch_state_sync(REDIS_URL, batch_id)
        if data and "status" in data:
            batch = {"batch_id": batch_id, **data}
            _batches[batch_id] = batch
        else:
            raise HTTPException(status_code=404, detail=f"batch_id {batch_id!r} not found")
    _sync_from_redis(batch, batch_id)
    return batch
```

**Why this matters:** Fixes Finding 3. Consultants won't get 404 errors if the API server restarts during a pipeline run.

**Claude Code prompt:**

```
Read api/routes/dynafit.py (specifically start_analysis and _get_batch functions).

1. In start_analysis, after creating the batch in _batches, also call RedisPubSub.write_batch_state_sync() to persist the initial state to Redis.
2. In _get_batch, if the batch is not in _batches, attempt recovery from Redis before raising 404.
3. Ensure all fields needed for the batch lifecycle are persisted: batch_id, status, upload_id, created_at, product, country, wave.

This makes the batch store crash-resilient without requiring a full database migration.
```

---

### Step 5: Parallelize Phase 4 LLM Calls

**Goal:** Reduce Phase 4 latency from ~120s to ~15s.

**Files to modify:**

- `modules/dynafit/nodes/classification.py` — batch LLM calls with asyncio.gather

**Changes:**

```python
# modules/dynafit/nodes/classification.py
# The classification node currently iterates atoms sequentially.
# Change to process in batches of 10 using asyncio.gather.

import asyncio
from concurrent.futures import ThreadPoolExecutor

BATCH_SIZE = 10  # Parallel LLM calls per batch (tunable)

def _classify_batch(atoms_batch, contexts, match_results, config):
    """Classify a batch of atoms in parallel."""
    loop = asyncio.new_event_loop()
    try:
        tasks = [
            _classify_single_atom(atom, contexts, match_results, config)
            for atom in atoms_batch
        ]
        return loop.run_until_complete(asyncio.gather(*tasks))
    finally:
        loop.close()

# In the main classification loop:
for i in range(0, len(atoms), BATCH_SIZE):
    batch = atoms[i:i + BATCH_SIZE]
    results = _classify_batch(batch, contexts, match_results, config)
    for result in results:
        # Emit per-atom classification event (from Step 2)
        publish_classification(...)
        all_classifications.append(result)
```

**Why this matters:** Fixes Finding 4. The single biggest latency bottleneck in the pipeline. With parallel batches of 10, the 80 LLM calls complete in ~12-15s instead of ~120s. The consultant's total wait time drops from ~2 minutes to ~30 seconds.

**Important constraint:** The platform's `LLMClient` handles retry logic and rate limiting. The parallelism must respect the `platform/llm/client.py` retry boundaries. Use a semaphore to cap concurrent requests at the LLM provider's rate limit.

**Claude Code prompt:**

```
Read modules/dynafit/nodes/classification.py and platform/llm/client.py.

The classification node currently processes atoms sequentially. Refactor to process in parallel batches:

1. Add a CLASSIFICATION_CONCURRENCY setting (default 10) to the module.
2. Use asyncio.Semaphore to limit concurrent LLM calls.
3. Process atoms in batches using asyncio.gather with the semaphore.
4. After each atom completes (not after each batch), emit the classification WebSocket event so the consultant sees results stream in.
5. Preserve the existing error handling: if an LLM call fails after retries, mark the atom as REVIEW_REQUIRED.
6. Ensure the Celery worker's event loop is used (the task already uses asyncio.run).

The per-atom emission order may differ from input order — this is acceptable because the frontend sorts by confidence.
```

---

### Step 6: Deduplicate Journey and Results in Redis

**Goal:** Reduce Redis memory usage and deserialization overhead by ~40%.

**Files to modify:**

- `modules/dynafit/presentation.py` — merge results into journey structure
- `api/workers/tasks.py` — write single unified blob
- `api/routes/dynafit.py` — derive results from journey

**Changes:**

The journey data already contains everything in the results data. Instead of storing both:

```python
# api/workers/tasks.py — _finish_complete
# CURRENT: writes both "results" and "journey" as separate JSON blobs
# CHANGE: write only "journey" (which includes everything results has)
# Derive "results" from "journey" at read time

_write_batch_state(
    batch_id,
    status="complete",
    journey=json.dumps(data["journey"]),  # single source of truth
    summary=json.dumps(data["summary"]),
    report_path=data["report_path"],
    completed_at=datetime.now(UTC).isoformat(),
)
```

```python
# api/routes/dynafit.py — derive results from journey
def _derive_results_from_journey(journey: list[dict]) -> list[dict]:
    """Extract results-table fields from journey data."""
    return [
        {
            "atom_id": j["atom_id"],
            "requirement_text": j["ingest"]["requirement_text"],
            "module": j["ingest"]["module"],
            "classification": j["output"]["classification"],
            "confidence": j["output"]["confidence"],
            "rationale": j["classify"]["rationale"],
            "d365_capability": j["classify"]["d365_capability"],
            "d365_navigation": j["classify"]["d365_navigation"],
            "config_steps": j["output"]["config_steps"],
            "gap_description": j["output"]["gap_description"],
            "gap_type": j["output"].get("gap_type"),
            "dev_effort": j["output"].get("dev_effort"),
            "reviewer_override": j["output"].get("reviewer_override", False),
        }
        for j in journey
    ]
```

**Why this matters:** Fixes Finding 5. For 50 atoms, saves ~100KB of redundant Redis storage and eliminates double-deserialization on every API call.

**Claude Code prompt:**

```
Read api/workers/tasks.py (_finish_complete and _finish_hitl), api/routes/dynafit.py (get_results, _sync_from_redis), and modules/dynafit/presentation.py (build_complete_data).

1. In _finish_complete, stop writing "results" as a separate Redis key. Only write "journey" and "summary".
2. In _sync_from_redis, when loading results, if "results" is empty but "journey" exists, derive results from journey.
3. Add a _derive_results_from_journey helper that extracts the flat results list from journey data.
4. Ensure backward compatibility: if "results" already exists in Redis (from a batch processed before this change), use it directly.

This is a storage optimization that reduces Redis memory and serialization overhead.
```

---

### Step 7: Add Batch State Index for Dashboard Performance

**Goal:** The `/batches` endpoint currently has no efficient way to list all batches. As the system scales, scanning Redis becomes slow.

**Files to modify:**

- `platform/storage/redis_pub.py` — maintain a sorted set index
- `api/workers/tasks.py` — register batch in index on creation
- `api/routes/dynafit.py` — query index for batch list

**Changes:**

```python
# platform/storage/redis_pub.py — ADD index methods

@staticmethod
def register_batch_sync(redis_url: str, batch_id: str, created_at: str) -> None:
    """Add batch to the sorted set index (score = timestamp)."""
    import redis as sync_redis
    r = sync_redis.from_url(redis_url)
    try:
        score = datetime.fromisoformat(created_at).timestamp()
        r.zadd("batches:index", {batch_id: score})
    finally:
        r.close()

@staticmethod
def list_batches_sync(redis_url: str, offset: int = 0, limit: int = 20) -> list[str]:
    """List batch IDs from sorted set, newest first."""
    import redis as sync_redis
    r = sync_redis.from_url(redis_url)
    try:
        return [
            b.decode() for b in
            r.zrevrange("batches:index", offset, offset + limit - 1)
        ]
    finally:
        r.close()
```

**Claude Code prompt:**

```
Read platform/storage/redis_pub.py, api/routes/dynafit.py (get_batches endpoint), and api/workers/tasks.py.

1. Add register_batch_sync and list_batches_sync static methods to RedisPubSub using a Redis sorted set "batches:index" with created_at timestamp as score.
2. In the start_analysis route (api/routes/dynafit.py), call register_batch_sync after creating the batch.
3. Modify get_batches to use list_batches_sync for pagination instead of iterating _batches dict.
4. Ensure the sorted set is populated for existing batches during _sync_from_redis if they're not already indexed.
```

---

## Part 5: Implementation Priority Matrix

| Step                              | Impact                           | Effort                              | Dependencies                   | Priority |
| --------------------------------- | -------------------------------- | ----------------------------------- | ------------------------------ | -------- |
| Step 1: Progress REST endpoint    | HIGH — fixes page refresh        | LOW — 1 endpoint + hook change      | None                           | P0       |
| Step 2: Stream per-atom journey   | CRITICAL — core UX improvement   | MEDIUM — refactor presentation + WS | None                           | P0       |
| Step 3: Batch-load journey data   | HIGH — eliminates N+1            | LOW — response shape change         | Step 2 (shared journey format) | P1       |
| Step 4: Persist batch to Redis    | HIGH — crash resilience          | LOW — 2 lines + recovery logic      | None                           | P0       |
| Step 5: Parallelize Phase 4       | CRITICAL — 10x latency reduction | MEDIUM — async refactor             | None                           | P0       |
| Step 6: Deduplicate Redis data    | MEDIUM — storage optimization    | LOW — read-derive pattern           | Step 3 (same data model)       | P2       |
| Step 7: Batch index for dashboard | MEDIUM — scales batch listing    | LOW — sorted set + query            | Step 4 (Redis persistence)     | P2       |

**Recommended execution order:** Step 4 → Step 1 → Step 5 → Step 2 → Step 3 → Step 6 → Step 7

---

## Part 6: Frontend Optimization — Additional Quick Wins

### Quick Win A: Debounce Filter Changes on Results Page

```typescript
// ui/src/pages/ResultsPage.tsx
// Currently, every filter change immediately triggers a new API call.
// Add 300ms debounce to prevent rapid-fire requests during typing.

const debouncedQuery = useDebouncedValue(query, 300);
const { data, isLoading } = useResults(batchId!, debouncedQuery);
```

**Claude Code prompt:** `Read ui/src/pages/ResultsPage.tsx. Add a useDebouncedValue hook (or use lodash.debounce) to debounce the query state by 300ms before passing it to useResults. This prevents API calls on every keystroke when filtering.`

### Quick Win B: Prefetch Next Page of Results

```typescript
// ui/src/hooks/useResults.ts
// Add prefetch for page+1 when the current page loads

const queryClient = useQueryClient();
useEffect(() => {
  if (data && query.page < totalPages) {
    queryClient.prefetchQuery({
      queryKey: ["results", batchId, { ...query, page: query.page + 1 }],
      queryFn: () => getResults(batchId, { ...query, page: query.page + 1 }),
    });
  }
}, [data, query.page]);
```

**Claude Code prompt:** `Read ui/src/hooks/useResults.ts. Add result prefetching: when the current page loads successfully, use queryClient.prefetchQuery to pre-load the next page. This eliminates the loading delay when the consultant clicks "Next".`

### Quick Win C: Skeleton Loading for Evidence Panel

```typescript
// ui/src/components/results/EvidencePanel.tsx
// When journey data is loading (fallback path), show skeleton instead of blank space

if (!journey) return <EvidenceSkeleton />
```

**Claude Code prompt:** `Read ui/src/components/results/EvidencePanel.tsx. Add a skeleton loading state that shows placeholder content (gray bars) while journey data is loading. Use the existing Skeleton component from ui/src/components/ui/Skeleton.tsx.`

---

## Part 7: Architecture Observation — Future Consideration

### Move from In-Memory Dict to Redis-Only State

The current `_batches` dict in `api/routes/dynafit.py` creates a dual-write problem. Every state mutation must update both `_batches` AND Redis. Steps 4 and 6 above mitigate this, but the long-term fix is to remove `_batches` entirely and use Redis as the single source of truth. This enables horizontal scaling of the FastAPI process (multiple replicas share Redis).

This is NOT included in the step-by-step plan because it's a larger refactor that should be its own PR after the above optimizations land.

---

## Part 8: Summary of Consultant Experience Transformation

**Before these changes:**

1. Upload → stare at progress bar for 2 minutes
2. Page refresh = lose all progress, start watching again
3. Results load → click each row → wait for journey API call
4. No ability to review results until entire batch completes

**After these changes:**

1. Upload → watch each classification stream in with full evidence
2. Page refresh = progress state restored instantly from Redis
3. Results load with all journey data inline — instant expand
4. Start reviewing high-confidence results while remaining items still process
5. Pipeline completes in ~30s instead of ~120s (parallel LLM calls)

Total consultant time savings: **~70% reduction in wait time** per batch.
