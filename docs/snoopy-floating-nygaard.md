# Plan: Per-Phase Analyst Gates for DYNAFIT

## Context

Analysts need visibility between pipeline phases to verify results before proceeding. Currently phases 1–4 run uninterrupted and only HITL review (Phase 5) can pause execution. This plan adds analyst-controlled gates after each phase: the pipeline pauses, displays what was produced, and waits for a "Proceed" click before running the next phase.

---

## New Batch Status State Machine

```
queued → processing → gate_1 → processing → gate_2 → processing
       → gate_3 → processing → gate_4 → processing
       → complete | review_required | error
```

`gate_N` statuses are written to both Redis `status` field and Postgres `batches.status` (already a `VARCHAR` — no migration needed).

---

## Key Design Decision

**Gate events are published by the Celery task** (not inside phase nodes). After `graph.ainvoke()` returns at each `interrupt_before` point, the task:
1. Extracts atom summaries from the returned state dict
2. Persists summaries to Redis (`phase1_atoms`, `phase2_contexts`, `phase3_matches` fields)
3. Sets `status=gate_N` in Redis + Postgres
4. Publishes `PhaseGateEvent` to Redis pub/sub (→ WebSocket)
5. Exits — LangGraph checkpoint persists in Postgres

Phase nodes are unchanged (no gate awareness).

---

## Backend Changes (9 files)

### 1. `platform/schemas/events.py`
Add `PhaseGateEvent` class and add to `ProgressEvent` union:
```python
class PhaseGateEvent(PlatformModel):
    event: Literal["phase_gate"] = "phase_gate"
    batch_id: str
    gate: Annotated[int, Field(ge=1, le=4)]
    phase_name: str
    atoms_count: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
```
Add `PhaseGateEvent` to the `ProgressEvent` discriminated union.

### 2. `platform/storage/redis_pub.py`
- Add `PhaseGateEvent` to the `TypeAdapter` union and `_TERMINAL` set (stops the pub/sub loop like `ReviewRequiredEvent`)
- Add static method `persist_gate_data_sync(redis_url, batch_id, field, rows: list[dict])` — writes JSON to a new Redis hash field

### 3. `modules/dynafit/graph.py`
Change `interrupt_before` to pause before all intermediate phases:
```python
interrupt_before=["retrieve", "match", "classify", "validate"]
```

### 4. `api/workers/tasks.py`

**Add `_proceed_from_gate` early-exit branch** (before `_resume` check, before `PipelineConfig` parsing):
```python
if config.get("_proceed_from_gate"):
    asyncio.run(_proceed_phase(batch_id, config["_proceed_from_gate"], thread_config))
    return
```

**Modify `_run_all_and_finish()`** — remove `_run_phase5()` call; after `graph.ainvoke(initial)` returns (phase 1 done, paused before retrieve):
```python
# Extract gate 1 data from returned state
phase1_rows = _extract_gate1_rows(state)
RedisPubSub.persist_gate_data_sync(REDIS_URL, batch_id, "phase1_atoms", phase1_rows)
await _update_batch_status_sync(batch_id, "gate_1", pg)
RedisPubSub.write_batch_state_sync(REDIS_URL, batch_id, status="gate_1")
gate_event = PhaseGateEvent(batch_id=batch_id, gate=1, phase_name="Ingestion", atoms_count=len(phase1_rows))
RedisPubSub.publish_sync(REDIS_URL, gate_event)
# Task exits — checkpoint preserved in Postgres
```

**Add `_proceed_phase(batch_id, gate, thread_config)` async helper**:
```python
async def _proceed_phase(batch_id, proceed_from_gate, thread_config):
    pg = PostgresStore(POSTGRES_ASYNC_URL)
    try:
        await pg.ensure_schema()
        await _update_batch_status_sync(batch_id, "processing", pg)
        RedisPubSub.write_batch_state_sync(REDIS_URL, batch_id, status="processing")

        async with AsyncPostgresSaver.from_conn_string(...) as checkpointer:
            graph = build_dynafit_graph(checkpointer=checkpointer)
            state = await graph.ainvoke(None, config=thread_config)  # runs next phase, pauses at next interrupt

            if proceed_from_gate == 1:
                rows = _extract_gate2_rows(state)
                RedisPubSub.persist_gate_data_sync(REDIS_URL, batch_id, "phase2_contexts", rows)
                _publish_gate(batch_id, gate=2, phase_name="RAG", count=len(rows), pg=pg)
            elif proceed_from_gate == 2:
                rows = _extract_gate3_rows(state)
                RedisPubSub.persist_gate_data_sync(REDIS_URL, batch_id, "phase3_matches", rows)
                _publish_gate(batch_id, gate=3, phase_name="Matching", count=len(rows), pg=pg)
            elif proceed_from_gate == 3:
                # Phase 4 just ran; classifications already in Redis (persisted atom-by-atom by phase 4 node)
                class_count = len(state.get("classifications", []))
                _publish_gate(batch_id, gate=4, phase_name="Classification", count=class_count, pg=pg)
            elif proceed_from_gate == 4:
                # Phase 5 just ran (validate node)
                if state.get("validated_batch"):
                    await _finish_complete(batch_id, state, pg)
                else:
                    flagged_ids, flagged_reasons = await _extract_interrupt_payload(graph, thread_config)
                    await _finish_hitl(batch_id, state, flagged_ids, flagged_reasons, pg)
    finally:
        await pg.dispose()
```

**Add `_extract_gate*_rows()` helpers** — pure functions that extract summary dicts from returned state:
- `_extract_gate1_rows(state)` → from `state["validated_atoms"]`: `{atom_id, requirement_text, intent, module, priority, completeness_score, specificity_score}`
- `_extract_gate2_rows(state)` → from `state["retrieval_contexts"]`: `{atom_id, requirement_text, top_capability, top_capability_score, retrieval_confidence}`
- `_extract_gate3_rows(state)` → from `state["match_results"]`: `{atom_id, requirement_text, composite_score, route, anomaly_flags}`

**Move interrupt payload extraction** from `_run_phase5()` to a reusable `_extract_interrupt_payload(graph, thread_config)` helper.

### 5. `api/models.py`
Add:
```python
class ProceedResponse(BaseModel):
    batch_id: str
    status: Literal["proceeding"] = "proceeding"
    next_phase: int

class Phase1AtomRow(BaseModel):  # + Phase2ContextRow, Phase3MatchRow
    atom_id: str
    requirement_text: str
    intent: str; module: str; priority: str
    completeness_score: float; specificity_score: float

class GateAtomsResponse(BaseModel):
    batch_id: str; gate: int
    rows: list[dict]
```

### 6. `api/routes/dynafit.py`
Add two endpoints:

**`POST /d365_fo/dynafit/{batch_id}/proceed`** → validates batch is in `gate_N` status, writes `processing` to Redis immediately (prevents poll window race), dispatches `run_dynafit_pipeline.delay(batch_id, "", {"_proceed_from_gate": N})`, returns `ProceedResponse`.

**`GET /d365_fo/dynafit/{batch_id}/gate/{gate}/atoms`** → reads gate-specific Redis field (`phase1_atoms`/`phase2_contexts`/`phase3_matches`/`classifications`), returns `GateAtomsResponse`.

Add `_dispatch_proceed(batch_id, gate)` helper following the existing `_dispatch_resume()` pattern.

### 7. `api/websocket/progress.py`
Update `_catch_up()` to handle gate statuses. After the `review_required` check block, add:
```python
if status and status.startswith("gate_"):
    gate = int(status.split("_")[1])
    # Replay phases first (already done above), then send gate event
    gate_event = PhaseGateEvent(batch_id=batch_id, gate=gate, ...)
    await websocket.send_text(gate_event.model_dump_json())
    return True  # Terminal for now — no live events until Proceed
```

---

## Frontend Changes (5 files)

### 8. `ui/src/api/types.ts`
```typescript
// Extend WSMessage union
export interface WSPhaseGate {
  event: 'phase_gate'; batch_id: string; gate: 1|2|3|4; phase_name: string; atoms_count: number; timestamp: string
}
export type WSMessage = ... | WSPhaseGate  // add to union

// Gate row types
export interface Phase1AtomRow { atom_id: string; requirement_text: string; intent: string; module: string; priority: string; completeness_score: number; specificity_score: number }
export interface Phase2ContextRow { atom_id: string; requirement_text: string; top_capability: string; top_capability_score: number; retrieval_confidence: 'HIGH'|'MEDIUM'|'LOW' }
export interface Phase3MatchRow { atom_id: string; requirement_text: string; composite_score: number; route: string; anomaly_flags: string[] }
export interface GateAtomsResponse { batch_id: string; gate: number; rows: Phase1AtomRow[]|Phase2ContextRow[]|Phase3MatchRow[]|ProgressClassificationItem[] }
export interface ProceedResponse { batch_id: string; status: 'proceeding'; next_phase: number }
```

### 9. `ui/src/api/dynafit.ts`
Add:
```typescript
export async function proceedGate(batchId: string): Promise<ProceedResponse>  // POST /proceed
export async function getGateAtoms(batchId: string, gate: number): Promise<GateAtomsResponse>  // GET /gate/{n}/atoms
```

### 10. `ui/src/stores/progressStore.ts`
- Add `activeGate: 1|2|3|4|null` to `ProgressState`, init as `null`
- Add `case 'phase_gate': return { activeGate: msg.gate }` in `dispatch()`
- In `case 'phase_start':` clear gate: `activeGate: null` (next phase started)
- In `hydrateFromProgress()`: if `data.status?.startsWith('gate_')` → extract and set `activeGate`

### 11. New `ui/src/components/progress/PhaseGatePanel.tsx`
```tsx
// Props: batchId, gate (1-4), onProceed, proceeding
// On mount: fetch getGateAtoms(batchId, gate) → render table
// Table columns are gate-specific (see below)
// Gate 4: skip table (LiveClassTable already visible above); show only header + Proceed button
// "Proceed to Phase N+1" button calls onProceed()
```

Gate-specific columns:
| Gate | Columns |
|------|---------|
| 1 | Req text, Intent, Module, Priority, Completeness |
| 2 | Req text, Top D365 Capability, Score, Confidence |
| 3 | Req text, Match Score, Route, Anomaly Flags |
| 4 | (no table — LiveClassTable already visible) |

### 12. `ui/src/pages/ProgressPage.tsx`
```tsx
const { activeGate, ... } = useProgress(batchId!)
const [proceeding, setProceeding] = useState(false)

const handleProceed = async () => {
  setProceeding(true)
  try { await proceedGate(batchId!) }
  catch { addNotification({ type: 'error', message: 'Failed to proceed.' }) }
  finally { setProceeding(false) }
}

// In JSX, between PhaseTimeline and PhaseStatsCards:
{activeGate && !complete && !reviewRequired && (
  <PhaseGatePanel batchId={batchId!} gate={activeGate} onProceed={handleProceed} proceeding={proceeding} />
)}

// Update isRunning to exclude gate state:
const isRunning = !complete && !error && !reviewRequired && !activeGate
```

---

## Implementation Order

1. `platform/schemas/events.py` — add `PhaseGateEvent` (everything imports this)
2. `platform/storage/redis_pub.py` — add `PhaseGateEvent` to adapter + `persist_gate_data_sync`
3. `modules/dynafit/graph.py` — expand `interrupt_before`
4. `api/workers/tasks.py` — add `_proceed_from_gate` branch, modify `_run_all_and_finish`, add `_proceed_phase` + extraction helpers
5. `api/models.py` — add response models
6. `api/routes/dynafit.py` — add two endpoints + `_dispatch_proceed`
7. `api/websocket/progress.py` — update `_catch_up` for gate statuses
8. Frontend: `types.ts` → `dynafit.ts` → `progressStore.ts` → `PhaseGatePanel.tsx` → `ProgressPage.tsx`

---

## Verification

1. Upload a file and start analysis
2. After Phase 1: WS delivers `phase_gate {gate: 1}`, `PhaseGatePanel` appears with parsed atoms table. `GET /gate/1/atoms` returns rows.
3. Click "Proceed to Phase 2": `POST /proceed` returns 202, pipeline resumes
4. After Phase 2: `phase_gate {gate: 2}` arrives, panel shows retrieval confidence table
5. After Phase 3: `phase_gate {gate: 3}` arrives, panel shows match scores table
6. After Phase 4: `phase_gate {gate: 4}` arrives, panel shows "Proceed to Validation" button (no table — LiveClassTable already visible)
7. After Phase 5: normal `complete` or `review_required` flow unchanged
8. Reconnect during any gate: `_catch_up` replays phases then sends `PhaseGateEvent` → correct gate state restored
