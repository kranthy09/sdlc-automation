# Session G — Phase 5: Validation, HITL + Output

> One session. Confirm this session before writing code.
> Read `docs/specs/dynafit.md` (PHASE 5 section) and `docs/specs/guardrails.md` (G10-lite + HITL) before
> modifying any file here.

---

## Goal

Replace the `validation_node` stub with the complete Phase 5 pipeline.

**Testable milestone:** Full pipeline end-to-end — classifications in, HITL roundtrip, FDD CSVs out.
`ValidatedFitmentBatch` correct counts, postgres write-back called, `CompleteEvent` published.

---

## Two Sub-Phases (execute sequentially)

Phase 5 is divided at the natural LangGraph `interrupt()` boundary:

| Sub-phase | Deliverables | Testable milestone |
|-----------|-------------|-------------------|
| **5A** — Sanity Gate + HITL | `guardrails.py` + first-pass logic in `phase5_validation.py` | `run_sanity_check()` flags per spec; `interrupt()` called iff flagged items exist |
| **5B** — Resume + Output Builder | Resume path in `phase5_validation.py` (merge → write-back → CSV → CompleteEvent) | Overrides merged, postgres called per result, two FDD CSVs written, `CompleteEvent` counts match batch |

---

## Sub-phase 5A: Sanity Gate + HITL Checkpoint

### Files to create

```
modules/dynafit/guardrails.py           ← G10-lite run_sanity_check()
modules/dynafit/nodes/phase5_validation.py  ← ValidationNode.__call__ + _check_flags()
tests/unit/test_phase5_guardrails.py    ← G10-lite unit tests (no Docker)
tests/integration/test_phase5.py        ← first-pass + interrupt path tests
```

### Platform utilities called

| Utility | Purpose |
|---------|---------|
| `platform/observability/logger.py` `get_logger()` | Phase entry/exit audit |
| `platform/storage/redis_pub.py` `RedisPubSub.publish()` | `PhaseStartEvent` before interrupt |
| `langgraph.types.interrupt()` | Freeze state, wait for human reviewer |

### Guardrails integrated

**G10-lite** (`modules/dynafit/guardrails.py`): three rules applied before HITL.

```python
def run_sanity_check(
    result: ClassificationResult,
    match: MatchResult,
    config: ProductConfig,
) -> list[str]:
    """
    Rule 1 — high_confidence_gap:
        result.confidence > config.fit_confidence_threshold AND classification == GAP
        Why: high confidence implies strong evidence; GAP verdict is suspicious.

    Rule 2 — low_score_fit:
        match.top_composite_score < config.review_confidence_threshold AND classification == FIT
        Why: weak similarity score but LLM said FIT — numbers don't support the verdict.

    Rule 3 — llm_schema_retry_exhausted:
        result.route_used == RouteLabel.REVIEW_REQUIRED
        Why: LLM failed to produce valid structured output after max retries.

    CRITICAL: never flip result.classification. Only return flags. Human decides.
    """
```

Additional flags from `ValidationNode._check_flags()`:
- `low_confidence`: `result.confidence < config.review_confidence_threshold` on non-GAP results
- `phase3_anomaly`: `match.anomaly_flags` is non-empty

### HITL flow

```
for each classification result:
    flags = _check_flags(result, match, config)
    if flags → flagged; else → clean

if flagged:
    publish PhaseStartEvent(phase=5, phase_name="human_review") → Redis
    log.info("hitl_checkpoint", flagged_count=...)
    overrides = interrupt({"batch_id": ..., "flagged_count": ..., "flagged_atom_ids": [...]})
    # graph freezes; PostgreSQL checkpoint preserves full state
    # API layer (Layer 4) handles reviewer interactions

# graph resumes here with overrides dict
```

### 5A test cases

```
test_no_flags_clean_pass → interrupt() not called, batch built immediately
test_sanity_high_confidence_gap → "high_confidence_gap" flag
test_sanity_low_score_fit → "low_score_fit" flag
test_sanity_llm_schema_retry_exhausted → "llm_schema_retry_exhausted" flag
test_multiple_flags_same_atom → all flags returned
test_clean_atom_no_flags → empty flags
test_confidence_filter_non_gap_below_threshold → "low_confidence" flag
test_phase3_anomaly_flag → "phase3_anomaly" flag
test_interrupt_called_with_correct_payload → interrupt called; payload has batch_id + flagged_atom_ids
test_all_results_flagged → all go to flagged queue
```

### 5A done criteria

- `make test-unit` passes with `tests/unit/test_phase5_guardrails.py`
- `run_sanity_check()` unit tests cover all three rules + edge cases
- ValidationNode first-pass tests confirm flagged queue population and interrupt call

---

## Sub-phase 5B: Resume + Output Builder

### Files modified

```
modules/dynafit/nodes/phase5_validation.py  ← _merge_overrides(), _write_csv(), _write_back()
tests/integration/test_phase5.py            ← resume path tests added
```

### Platform utilities called

| Utility | Purpose |
|---------|---------|
| `platform/retrieval/embedder.py` `Embedder.embed()` | Embed requirement text for pgvector write-back |
| `platform/storage/postgres.py` `PostgresStore.save_fitment()` | Write-back each finalized result |
| `platform/storage/redis_pub.py` `RedisPubSub.publish()` | `CompleteEvent` after batch complete |

### Override merge contract

`interrupt()` returns `dict[str, dict | None]` keyed by `atom_id`:
- `None` → human approved original classification (no change)
- `{"classification": "FIT", "rationale": "...", "consultant": "reviewer@co.com"}` → human override

`_merge_overrides(clean, flagged, overrides)` → `list[_MergedResult]` where each carries
`(result, reviewer_override: bool, consultant: str | None)`.

### Output: FDD CSVs

Two files written to `reports/{batch_id}/`:

| File | Contents |
|------|---------|
| `fdd_fits_{batch_id}.csv` | All FIT + PARTIAL_FIT results |
| `fdd_gaps_{batch_id}.csv` | All GAP results |

**CSV columns (stdlib `csv`):**
`req_id, requirement, module, country, wave, classification, confidence,`
`d365_capability, rationale, config_steps, gap_description, reviewer, override`

### Write-back rules

- FIT, PARTIAL_FIT, GAP → `postgres.save_fitment()` + embed
- REVIEW_REQUIRED → skipped (not final; cannot be persisted per `postgres.py` contract)
- If `save_fitment` raises `PostgresError` → `log.warning()` + continue (write-back is not
  pipeline-critical; batch completes regardless)

### 5B test cases

```
test_override_applied → classification changed in final batch
test_override_none_preserves_original → approved items keep original classification
test_reviewer_override_flag_in_write_back → save_fitment called with reviewer_override=True
test_review_required_not_written_to_postgres → save_fitment not called for REVIEW_REQUIRED
test_batch_counts_sum_to_total → ValidatedFitmentBatch validator passes
test_fdd_fits_csv_written → fdd_fits CSV exists with FIT+PARTIAL rows
test_fdd_gaps_csv_written → fdd_gaps CSV exists with GAP rows
test_csv_header_columns → all 13 columns present
test_complete_event_published → redis.publish called with CompleteEvent + correct counts
test_write_back_postgres_error_logged_not_raised → postgres failure → log warning, batch completes
test_validation_node_singleton_smoke → module-level validation_node() creates singleton
```

### 5B done criteria

- `make test-unit` and `make test-integration` (mocked infra) pass
- `ValidatedFitmentBatch.counts_sum_to_total` validator never fails in tests
- Both FDD CSVs have correct headers and row counts
- `CompleteEvent` published as final Redis event

---

## Files created (full list)

```
modules/dynafit/guardrails.py
modules/dynafit/nodes/phase5_validation.py   ← replaces stub
tests/unit/test_phase5_guardrails.py
tests/integration/test_phase5.py
```

---

## Verification

```bash
make test-unit        # test_phase5_guardrails.py + node singleton smoke
make test-integration # full Phase 5 with mocked infra (no Docker needed)
make validate-contracts  # confirm no platform ← module import violations
```
