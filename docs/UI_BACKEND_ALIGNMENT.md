# Phase 5 UI ↔ Backend Alignment Report

**Status**: ✅ COMPLETE | All three issues fully aligned

---

## Issue #1: G10-lite Scope Consolidation

### Backend Implementation
✅ **modules/dynafit/guardrails.py** — 8 consolidated rules
- Rules 1-3: G10-lite (high_confidence_gap, low_score_fit, llm_schema_retry_exhausted)
- Rules 4-8: Phase 5 validation (low_confidence, gap_review, phase3_anomaly, response_pii_leak, partial_fit_no_config)

✅ **modules/dynafit/presentation.py** — review_reason() mapping function (line 29-39)
```python
def review_reason(flags: list[str]) -> str:
  if "response_pii_leak" in flags:
    return "pii_detected"
  if "gap_review" in flags:
    return "gap_review"
  if "partial_fit_no_config" in flags:
    return "partial_fit_no_config"
  if any(f in _ANOMALY_FLAG_NAMES for f in flags):
    return "anomaly"
  return "low_confidence"
```

Mapping Matrix:
| Backend Flags | UI review_reason |
|---|---|
| response_pii_leak | pii_detected |
| gap_review | gap_review |
| partial_fit_no_config | partial_fit_no_config |
| high_confidence_gap, low_score_fit, llm_schema_retry_exhausted, phase3_anomaly | anomaly |
| low_confidence (and others) | low_confidence |

### UI Implementation (FIXED)

✅ **ui/src/api/types.ts** — ReviewItem type
```typescript
review_reason: 'low_confidence' | 'anomaly' | 'pii_detected' | 'gap_review' | 'partial_fit_no_config'
```

✅ **ui/src/components/review/ReviewCard.tsx** — Reason labels & colors
```typescript
const REASON_LABEL: Record<ReviewItem['review_reason'], string> = {
  low_confidence: 'Low confidence',
  anomaly: 'Anomaly detected',
  pii_detected: 'PII detected in response',
  gap_review: 'GAP — requires sign-off',
  partial_fit_no_config: 'PARTIAL_FIT — config steps missing',
}
```

✅ **ui/src/components/progress/ReviewBanner.tsx** — Reason breakdown (FIXED)
Now displays all 5 review reasons with proper counts:
- low_confidence: "low confidence"
- anomaly: "anomaly"
- pii_detected: "PII detected"
- gap_review: "gap review"
- partial_fit_no_config: "missing config"

### Event Flow
1. Phase 5 validation flags atoms with rule names (e.g., "high_confidence_gap")
2. presentation.py::review_reason() maps to UI reason (e.g., "anomaly")
3. ReviewItem stored with review_reason field
4. API sends ReviewRequiredEvent with reasons_counts dict
5. WebSocket delivers to UI
6. progressStore.dispatch('review_required') extracts reasons
7. ReviewBanner & ReviewCard display with proper labels

---

## Issue #2: Missing phase_start Event

### Backend Implementation
✅ **modules/dynafit/nodes/phase5_validation.py** (lines 180-186)
```python
publish_phase_start(
    batch_id,
    phase=5,
    phase_name="Validation",
)
```
Event published unconditionally at Phase 5 entry (before any gates).

### UI Implementation (✅ ALREADY ALIGNED)

✅ **ui/src/api/types.ts** — WSPhaseStart type
```typescript
interface WSPhaseStart {
  event: 'phase_start'
  batch_id: string
  phase: number
  phase_name: string
  timestamp: string
}
```

✅ **ui/src/stores/progressStore.ts** — Event handler (line 183-184)
```typescript
case 'phase_start':
  return { phases: applyPhaseStart(state.phases, msg), activeGate: null }
```

✅ **ui/src/stores/progressStore.ts** — Phase application (line 92-105)
```typescript
function applyPhaseStart(phases: PhaseState[], msg: WSPhaseStart): PhaseState[] {
  return phases.map((p) => {
    if (p.phase === msg.phase) {
      return { ...p, status: 'active', phaseName: msg.phase_name }
    }
    // ... mark prior phases complete
  })
}
```

✅ **ui/src/pages/ProgressPage.tsx** — UI display (line 119)
```typescript
Phase {activePhase.phase}: {activePhase.phaseName}
```

### Event Flow
1. Phase 5 starts → publish_phase_start() called
2. Event published to Redis and WebSocket
3. UI receives via DynafitWebSocket
4. progressStore.dispatch('phase_start') → applyPhaseStart()
5. Phase 5 marked as active with name "Validation"
6. ProgressPage displays "Phase 5: Validation"

---

## Issue #3: No Step Progress Events

### Backend Implementation
✅ **modules/dynafit/nodes/phase5_validation.py** (lines 207-213, 239-246, 257-265)

Three milestone events published with context-aware progress:

**Checkpoint 1: After Sanity Gate**
```python
publish_step_progress(
    batch_id,
    phase=5,
    step="sanity_gate_complete",
    completed=1,
    total=3 if flagged else 2,
)
```

**Checkpoint 2: After HITL Review (flagged path only)**
```python
publish_step_progress(
    batch_id,
    phase=5,
    step="hitl_review_complete",
    completed=2,
    total=3,
)
```

**Checkpoint 3: After Output Generation**
```python
publish_step_progress(
    batch_id,
    phase=5,
    step="validation_output_generated",
    completed=3 if flagged else 2,
    total=3 if flagged else 2,
)
```

Progress Paths:
- **Clean (no flags)**: 1/2 → 2/2 (two events)
- **Flagged**: 1/3 → 2/3 → 3/3 (three events)

### UI Implementation (✅ ALREADY ALIGNED)

✅ **ui/src/api/types.ts** — WSStepProgress type
```typescript
interface WSStepProgress {
  event: 'step_progress'
  batch_id: string
  phase: number
  step: string
  completed: number
  total: number
  timestamp: string
}
```

✅ **ui/src/stores/progressStore.ts** — Event handler (line 186-187)
```typescript
case 'step_progress':
  return { phases: applyStepProgress(state.phases, msg) }
```

✅ **ui/src/stores/progressStore.ts** — Progress calculation (line 107-113)
```typescript
function applyStepProgress(phases: PhaseState[], msg: WSStepProgress): PhaseState[] {
  const pct = msg.total > 0 ? Math.round((msg.completed / msg.total) * 100) : 0
  return phases.map((p) =>
    p.phase === msg.phase
      ? { ...p, progressPct: pct, currentStep: msg.step }
      : p,
  )
}
```

✅ **ui/src/pages/ProgressPage.tsx** — Step display (line 120-121)
```typescript
{activePhase.currentStep && (
  <span className="ml-2 text-text-secondary">— {activePhase.currentStep}</span>
)}
```

### Event Flow
1. Phase 5 reaches milestones → publish_step_progress() called
2. Event includes step name and progress counters
3. WebSocket delivers to UI
4. progressStore.dispatch('step_progress') → applyStepProgress()
5. currentStep updated (e.g., "sanity_gate_complete")
6. progressPct recalculated (e.g., 50% = 1/2)
7. ProgressPage displays "Phase 5: Validation — sanity_gate_complete" with progress bar

---

## Files Modified (UI Alignment Only)

| File | Change | Lines |
|------|--------|-------|
| `ui/src/api/types.ts` | Updated WSReviewRequired.reasons to include all 5 reasons; Updated ReviewItem.review_reason type to remove "conflict" | 141, 399-404 |
| `ui/src/stores/progressStore.ts` | Updated ReviewRequiredState interface; Updated review_required event handler; Updated hydrate fallback | 41-50, 208-215, 304-311 |
| `ui/src/components/progress/ReviewBanner.tsx` | Complete rewrite to display all 5 review reasons with dynamic labels | Lines 1-48 |
| `ui/src/components/review/ReviewCard.tsx` | Removed "conflict" from REASON_LABEL and REASON_COLOR | 9-20 |

---

## Verification Checklist

### Issue #1: Guardrails Display
- [x] ReviewCard displays all 5 reason types (low_confidence, anomaly, pii_detected, gap_review, partial_fit_no_config)
- [x] ReviewBanner shows breakdown of all reason counts
- [x] Each reason has distinct visual styling (color + icon)
- [x] Mapping from backend flags to UI reasons is correct

### Issue #2: Phase Start
- [x] Phase 5 publishes phase_start unconditionally
- [x] UI receives and processes phase_start event
- [x] Phase marked as active when started
- [x] Phase name displayed as "Validation"

### Issue #3: Step Progress
- [x] Three step progress events published at correct milestones
- [x] Progress total adjusts for clean (2) vs flagged (3) paths
- [x] UI consumes step_progress events
- [x] currentStep displayed to user
- [x] Progress percentage calculated correctly

---

## Testing Recommendations

### Integration Tests
1. **Phase 5 entry**: Verify phase_start event published before any gates
2. **Clean path**: Verify 2 step progress events (1/2, 2/2) in clean pass
3. **Flagged path**: Verify 3 step progress events (1/3, 2/3, 3/3) in flagged pass
4. **Review reasons**: Verify ReviewRequiredEvent.reasons contains correct counts
5. **UI display**: Verify ReviewBanner shows all 5 reason types with counts
6. **UI styling**: Verify each reason type has correct color/icon in ReviewCard

### Frontend Smoke Tests
```bash
# Check TypeScript compilation
npm run type-check

# Verify Review component rendering
npm run test ui/src/components/review

# Verify Progress store event handling
npm run test ui/src/stores/progressStore
```

---

## Architecture Notes

### Two-System Design
The platform operates as **two synchronized systems**:

**System A: Backend (Python/LangGraph)**
- Executes phases sequentially
- Publishes events to Redis at phase/step boundaries
- Persists state to PostgreSQL (durable) and Redis (transient)

**System B: Frontend (React/TypeScript)**
- Subscribes to WebSocket (Redis events)
- Maintains in-memory Redux state (progressStore)
- Renders UI based on phase state + step progress

**Synchronization Points:**
- phase_start: Phase entry announced
- step_progress: Milestone reached within phase
- phase_complete: Phase finished with final counts
- review_required: Human review needed (HITL)
- complete: Pipeline finished

### Naming Consistency
- Backend flags: `high_confidence_gap`, `low_score_fit`, etc. (snake_case, 8 unique values)
- UI reasons: `low_confidence`, `anomaly`, `pii_detected`, `gap_review`, `partial_fit_no_config` (snake_case, 5 mapped values)
- Review reasons are deterministic based on flag set (many-to-one mapping)

