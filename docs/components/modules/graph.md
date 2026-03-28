# Graph — LangGraph DAG

**What:** Orchestrates 5 phases into a directed acyclic graph with checkpoints.

**File:** `modules/dynafit/graph.py`

**Runs:** Sequentially: Phase 1 → 2 → 3 → 4 → 5 → Complete

---

## Graph Structure

```
RawUpload
    ↓
[Phase 1: Ingestion]
    ↓
AtomizedBatch
    ↓
[Phase 2: RAG]
    ↓
RetrievalResults
    ↓
[Phase 3: Matching]
    ↓
MatchingResults
    ↓
[Phase 4: Classification]
    ↓
ClassificationResults
    ↓
[Phase 5: Validation] ← HITL checkpoint (interrupt)
    ↓
ValidatedFitmentBatch
    ↓
Complete
```

## Implementation Pattern

```python
from langgraph.graph import StateGraph
from platform.storage import PostgresStore

# 1. Define state schema
class BatchState(BaseModel):
    batch_id: str
    upload: RawUpload
    atoms: list[RequirementAtom] | None = None
    retrieval_results: list[RetrievalResult] | None = None
    matching_results: list[MatchingResult] | None = None
    classification_results: list[ClassificationResult] | None = None
    final_batch: ValidatedFitmentBatch | None = None

# 2. Create graph
graph_builder = StateGraph(BatchState)

# 3. Add nodes (the 5 phases)
graph_builder.add_node("phase_1_ingestion", phase1_ingestion)
graph_builder.add_node("phase_2_rag", phase2_rag)
graph_builder.add_node("phase_3_matching", phase3_matching)
graph_builder.add_node("phase_4_classification", phase4_classification)
graph_builder.add_node("phase_5_validation", phase5_validation)

# 4. Add edges (sequential)
graph_builder.add_edge("phase_1_ingestion", "phase_2_rag")
graph_builder.add_edge("phase_2_rag", "phase_3_matching")
graph_builder.add_edge("phase_3_matching", "phase_4_classification")
graph_builder.add_edge("phase_4_classification", "phase_5_validation")
graph_builder.add_edge("phase_5_validation", END)

# 5. Set entry point
graph_builder.set_entry_point("phase_1_ingestion")

# 6. Compile with PostgreSQL checkpointer
checkpointer = PostgresStore(
    connection_string=settings.postgres_dsn,
    namespace="dynafit_graph"
)
graph = graph_builder.compile(checkpointer=checkpointer)
```

## Running the Graph

```python
# From API or Celery task
async def run_batch(batch_id: str, upload: RawUpload):
    """Execute graph for a batch."""

    state = BatchState(batch_id=batch_id, upload=upload)

    config = {"configurable": {"thread_id": batch_id}}

    try:
        final_state = await graph.ainvoke(
            state,
            config=config
        )
        logger.info("batch_completed", batch_id=batch_id)
        return final_state.final_batch

    except LangGraphInterrupt as e:
        # Phase 5 HITL interrupt — graph paused, awaiting human
        logger.info("batch_awaiting_review", batch_id=batch_id)
        return None  # Graph frozen, UI shows review screen

    except Exception as e:
        logger.error("batch_failed", batch_id=batch_id, error=str(e))
        raise
```

## Checkpointing (State Persistence)

Each phase updates state. After each node, state is checkpointed to PostgreSQL:

```python
# After Phase 1 completes
state.atoms = [... atoms ...]
# checkpoint saved automatically

# After Phase 2 completes
state.retrieval_results = [... results ...]
# checkpoint saved automatically

# On Phase 5 interrupt
# checkpoint saved + graph paused
```

**Resume after HITL:**
```python
# User submits override in UI
# Call graph.ainvoke with same config (thread_id)
# LangGraph loads checkpoint, resumes from where it paused

final_state = await graph.ainvoke(
    state,
    config={"configurable": {"thread_id": batch_id}}
)
# Resumes at Phase 5, applies overrides, continues to completion
```

## Event Publishing

Each phase publishes events to Redis:

```python
# In each phase node, before returning
await redis.publish("phase_events", json.dumps({
    "batch_id": batch_id,
    "phase": 2,
    "phase_name": "RAG",
    "status": "completed",
    "timestamp": datetime.utcnow().isoformat()
}))
```

**UI subscribes:**
```javascript
socket.on("phase_completed", (data) => {
    console.log(`Phase ${data.phase} complete. Moving to Phase ${data.phase + 1}`);
});
```

## Error Handling

**Phase succeeds:** State updated, continue to next phase.

**Phase fails with known error:** Log, set `phase_failed` flag, move to error handler node (optional).

**Phase fails with unknown error:** Log, raise, batch marked as failed.

**HITL interrupts:** Graph pauses, awaiting human.

## Testing

```python
@pytest.mark.asyncio
async def test_graph_runs_all_phases():
    """Full batch through all 5 phases."""
    upload = factories.make_raw_upload()
    batch_id = str(uuid4())

    state = BatchState(batch_id=batch_id, upload=upload)
    config = {"configurable": {"thread_id": batch_id}}

    final_state = await graph.ainvoke(state, config=config)

    assert final_state.atoms is not None
    assert final_state.retrieval_results is not None
    assert final_state.matching_results is not None
    assert final_state.classification_results is not None
    assert final_state.final_batch is not None
```

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — Node pattern (each phase)
- [phase1_ingestion.md](phase1_ingestion.md) → [phase5_validation.md](phase5_validation.md) — Each phase
- [storage.md](../platform/storage.md) — Checkpoint details
