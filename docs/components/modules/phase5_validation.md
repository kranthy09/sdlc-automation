# Phase 5 — Validation + HITL

**What:** Final sanity checks, human review (HITL), and audit.

**File:** `modules/dynafit/nodes/phase5_validation.py`

**Input:** `list[ClassificationResult]` from Phase 4

**Output:** `ValidatedFitmentBatch` — Final results + human overrides

---

## What It Does

1. **Run sanity gate** (G10-lite) — Flag suspicious results
2. **Check confidence** — High-confidence gaps, low-score fits
3. **Interrupt if flagged** — Publish event, wait for human
4. **Apply overrides** — Human decides: accept or override
5. **Build final batch** — Merge overrides, audit trail
6. **Emit complete event** — Batch ready for export

## Output Schema

```python
class ValidatedFitmentBatch(BaseModel):
    batch_id: str
    results: list[ClassificationResult]  # Final classifications
    flagged_for_review: list[ClassificationResult]  # Sent to human
    human_overrides: dict[str, str]  # atom_id -> new classification
    completed_at: datetime
    review_required: bool
```

## Implementation Pattern

```python
async def phase5_validation(
    classification_results: list[ClassificationResult]
) -> ValidatedFitmentBatch:
    """
    Step 1: Run sanity gate (G10-lite) on all results
    Step 2: Collect flagged items
    Step 3: If flagged, interrupt (HITL)
    Step 4: Apply human overrides
    Step 5: Return final batch
    """

    batch_id = classification_results[0].batch_id

    # 1. Sanity gate (G10-lite)
    flagged = []
    for result in classification_results:
        flags = sanity_check(result)
        if flags:
            result.flagged_for_review = True
            flagged.append(result)
            logger.warning("sanity_gate_flagged", atom_id=result.atom_id, flags=flags)

    # 2. If any flagged, interrupt
    if flagged:
        logger.info("hitl_required", count=len(flagged))

        # Publish event for UI
        await redis.publish("phase_events", json.dumps({
            "batch_id": batch_id,
            "phase": 5,
            "status": "awaiting_human_review",
            "flagged_count": len(flagged)
        }))

        # LangGraph interrupt: freeze, checkpoint state
        interrupt({"flagged_for_review": flagged, "batch_id": batch_id})
        # ^^^ This pauses the graph. UI shows review screen. Human decides.
        # When human submits, graph resumes from checkpoint.

    # 3. Apply overrides (comes from UI after interrupt)
    overrides = await get_human_overrides(batch_id)  # From DB
    for atom_id, new_classification in overrides.items():
        for result in classification_results:
            if result.atom_id == atom_id:
                result.classification = new_classification
                result.reviewed_by_human = True
                logger.info("override_applied", atom_id=atom_id, new=new_classification)

    # 4. Build final batch
    final_batch = ValidatedFitmentBatch(
        batch_id=batch_id,
        results=classification_results,
        flagged_for_review=flagged,
        human_overrides=overrides,
        completed_at=datetime.utcnow(),
        review_required=len(flagged) > 0
    )

    # 5. Emit complete event
    await redis.publish("phase_events", json.dumps({
        "batch_id": batch_id,
        "phase": 5,
        "status": "completed",
        "fit_count": sum(1 for r in classification_results if r.classification == "FIT"),
        "gap_count": sum(1 for r in classification_results if r.classification == "GAP"),
        "review_count": sum(1 for r in classification_results if r.classification == "REVIEW_REQUIRED")
    }))

    logger.info("batch_complete", batch_id=batch_id, result_count=len(classification_results))

    return final_batch
```

## Sanity Gate (G10-lite)

File: `modules/dynafit/guardrails.py`

```python
def sanity_check(result: ClassificationResult) -> list[str]:
    """
    Flags (NOT blocks):
      1. High confidence + GAP (seems unlikely)
      2. Low score + FIT (seems shaky)
      3. LLM schema exhausted (need review)

    NEVER flips classification. Only flags.
    Human decides in Phase 5 HITL.
    """
    flags = []

    if result.confidence > 0.85 and result.classification == "GAP":
        flags.append("high_confidence_gap")

    if result.composite_score < 0.60 and result.classification == "FIT":
        flags.append("low_score_fit")

    if result.route == "LLM_SCHEMA_RETRY_EXHAUSTED":
        flags.append("llm_schema_exhausted")

    return flags
```

## HITL (Human-In-The-Loop) Flow

### 1. Interrupt Triggered

When `flagged_for_review` is non-empty:
- LangGraph calls `interrupt(data)` → Pauses execution
- PostgreSQL saves checkpoint (full graph state)
- Redis publishes event: `{"status": "awaiting_human_review", ...}`

### 2. Human Reviews in UI

UI shows:
- Flagged atom ID, text, current classification
- Why it was flagged (sanity gate reason)
- Similar atoms from KB
- Suggested modules

Human can:
- Accept current classification
- Override to FIT/GAP/REVIEW_REQUIRED

### 3. Resume from Checkpoint

After human submits:
- UI calls API: `POST /batches/{id}/review/{atom_id}` → new classification
- API stores override in DB
- Phase 5 node resumes from checkpoint
- Merges overrides into classification results
- Continues to final output

### 4. Complete Event

Batch moves to final state:
- CSV report generated
- Final event published
- Audit trail saved

## API Endpoints (HITL)

```python
# GET /batches/{batch_id}/review
# Response: list of flagged items waiting for human decision

# POST /batches/{batch_id}/review/{atom_id}
# Body: {"classification": "FIT" | "GAP" | "REVIEW_REQUIRED"}
# Response: stored override, graph resumes
```

See [api_batches.md](../api/api_batches.md).

## Testing

```python
@pytest.mark.asyncio
async def test_phase5_no_flags():
    """No flagged items, batch completes immediately."""
    results = [factories.make_classification_result(confidence=0.5)]
    with patch("platform.storage.sanity_check") as mock:
        mock.return_value = []  # No flags
        batch = await phase5_validation(results)
        assert batch.review_required == False
        assert batch.flagged_for_review == []

@pytest.mark.asyncio
async def test_phase5_flags_high_confidence_gap():
    """Sanity gate flags high-confidence gaps."""
    result = factories.make_classification_result(
        classification="GAP",
        confidence=0.95
    )
    with patch("modules.dynafit.guardrails.sanity_check") as mock:
        mock.return_value = ["high_confidence_gap"]
        batch = await phase5_validation([result])
        assert batch.review_required == True
        assert result in batch.flagged_for_review

@pytest.mark.asyncio
async def test_phase5_applies_overrides():
    """Human overrides are merged into final results."""
    result = factories.make_classification_result(classification="FIT")
    with patch("modules.dynafit.guardrails.sanity_check") as mock:
        mock.return_value = []
        with patch("modules.dynafit.nodes.phase5_validation.get_human_overrides") as override_mock:
            override_mock.return_value = {result.atom_id: "GAP"}
            batch = await phase5_validation([result])
            # Verify override was applied
            assert batch.human_overrides[result.atom_id] == "GAP"
```

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — Node pattern
- [guardrails.md](../platform/guardrails.md) — G10-lite
- [api_batches.md](../api/api_batches.md) — HITL endpoints
- [storage.md](../platform/storage.md) — LangGraph checkpoints
