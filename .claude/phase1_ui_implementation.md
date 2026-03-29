# Phase 1 Ingestion Gate UI — Implementation Plan

## Summary of User Questions

1. **Requirement Text Truncation**: Currently truncated with "max-w-xs truncate" in the table
2. **Data Fields**: What 6+ fields come from the frontend for each atom?
3. **PII Flagging**: Where and how are flagged items shown?
4. **PII Logic**: What is the redaction/extraction logic?

---

## Current Architecture Analysis

### Backend (Python)

**Phase 1 Ingestion Flow:**
1. Parse document → extract atoms (RequirementAtom)
2. Scan for injection (G3-lite)
3. Redact PII (G2) → stores pii_redaction_map in DynafitState
4. Atomize & score (intent, module, completeness, specificity)
5. Apply quality gates → ValidatedAtom[] + FlaggedAtom[]

**PII Redaction (G2):**
- `platform/guardrails/pii_redactor.py`: redact_pii() returns PIIRedactionResult
  - redacted_text (with placeholders like `<PII_PERSON_1>`)
  - entities_found: list[PIIEntity] (type, start, end, score, placeholder)
  - redaction_map: {placeholder → original_text}
- Applied in `modules/dynafit/nodes/ingestion.py:_redact_one()` (line 350)
- Combined map stored in state.pii_redaction_map
- Used in Phase 5 to restore original text in final CSV output

**Data Available per Atom:**
- RequirementAtom: atom_id, requirement_text, source_file, source_page, intent, module, priority, country, req_id, upload_id, content_type, d365_modules_implied
- ValidatedAtom: All above + completeness_score (0-100), specificity_score (0-1)
- FlaggedAtom: atom_id, upload_id, requirement_text, flag_reason, flag_detail, specificity_score, source_refs

**What's Missing:**
- No per-atom tracking of which atoms have PII detected
- No PIIEntity list attached to atoms
- pii_redaction_map is global, not per-atom

### Frontend (React/TypeScript)

**Current Phase1AtomRow (ui/src/api/types.ts):**
```typescript
export interface Phase1AtomRow {
  atom_id: string
  requirement_text: string
  intent: string
  module: string
  priority: string
  completeness_score: number  // 0–100
  specificity_score: number   // 0–1
}
```

**Current UI (PhaseGatePanel.tsx):**
- Table with truncated requirement_text (max-w-xs truncate)
- Shows: Requirement | Intent | Module | Priority | Completeness | Specificity
- No PII information displayed
- Click-to-view not implemented

**Guardrail Status (GuardrailStatusCard.tsx):**
- Shows "10 items flagged for PII" count only
- No expandable list of which atoms have PII
- No details about what PII was detected

---

## Achievable Subtasks

### **Subtask 1: Extend Data Structures for PII Tracking**

**Goal:** Backend returns PII metadata with each Phase 1 atom

**Changes:**
1. Extend Phase1AtomRow to include PII info:
   ```typescript
   export interface Phase1AtomRow {
     // ... existing fields
     pii_detected: boolean
     pii_entities: Array<{
       entity_type: string  // PERSON, EMAIL_ADDRESS, PHONE_NUMBER, etc.
       original_text: string
       placeholder: string
       score: number
     }>
   }
   ```

2. Backend: Add PIIEntity tracking in ingestion.py
   - After redact_pii(), extract entity info for each atom
   - Store per-atom PII metadata in ValidatedAtom/FlaggedAtom
   - Return in gate atoms response

**Estimated Scope:**
- Backend: 2-3 files (ingestion.py, requirement.py schema, routes/batches.py)
- Frontend: types.ts only
- No UI changes needed yet

---

### **Subtask 2: Expand Requirement Text Display**

**Goal:** Show full requirement text instead of truncation

**Option A (Simple):** Add title attribute + increase max-width
```typescript
<td title={row.requirement_text} className="max-w-2xl truncate">
  {row.requirement_text}
</td>
```

**Option B (Better):** Click-to-expand inline modal
- Add expandable row or modal when clicking requirement text
- Show full text with line wrapping
- Show source file + page number
- Show original + redacted version side-by-side if PII detected

**Option C (Best):** Dedicated detail drawer
- Slide-out panel showing complete atom details
- Full requirement text, intent, module, priority, scores, PII info

**Recommended:** Option B for Phase 1 (inline expansion), escalate complex atoms to detail drawer

**Files:**
- ui/src/components/progress/PhaseGatePanel.tsx (add expandable row logic)
- ui/src/components/progress/RequirementDetailModal.tsx (NEW - modal component)

---

### **Subtask 3: Create PII Details Component**

**Goal:** Display which atoms have PII and what was detected

**Component:** RequirementPIIDetails.tsx
```typescript
interface RequirementPIIDetailsProps {
  entities: Array<{
    entity_type: string
    original_text: string
    score: number
  }>
  redactedText: string
  originalText: string
}

// Shows:
// - "PII Detected: 3 entities"
// - List of entity types with confidence scores
// - Original vs Redacted text comparison (collapsible)
```

**Files:**
- ui/src/components/progress/RequirementPIIDetails.tsx (NEW)
- Integrate into PhaseGatePanel table row expansion

---

### **Subtask 4: Enhance GuardrailStatusCard**

**Goal:** Show clickable list of PII-flagged atoms

**Changes to GuardrailStatusCard.tsx:**
- Change PII item from static "10 items flagged" to expandable list
- Show atom_ids with PII flags
- On click, jump to atom in table or open details panel
- Show entity type summary (e.g., "3 PERSON, 2 EMAIL_ADDRESS")

**Interaction:**
```
Guardrail Status
├─ File Validation ✓
├─ PII Redaction ⚠️ (10 items)
│  └─ Click to expand list
└─ Injection Scan ✓
```

---

### **Subtask 5: Add Atom Detail Drawer (Phase 1)**

**Goal:** Dedicated view for complete atom metadata

**Component:** Phase1AtomDetailCard.tsx or slide-out drawer
```
Requirement: [Full text - not truncated]
─────────────────────────
Atom ID: REQ-001
Intent: FUNCTIONAL
Module: Sales Management
Priority: MUST
Country: US
Source: requirements_2024.pdf, page 5
─────────────────────────
Quality Scores:
  Completeness: 92%
  Specificity: 0.87
─────────────────────────
PII Detected: Yes (2 entities)
  ├─ PERSON (score: 0.95)
  │  Original: "John Smith"
  │  Redacted: <PII_PERSON_1>
  └─ EMAIL_ADDRESS (score: 0.98)
     Original: john@company.com
     Redacted: <PII_EMAIL_1>
─────────────────────────
Actions:
  [ View Original ] [ Pin ] [ Export ]
```

**Files:**
- ui/src/components/results/Phase1DetailCard.tsx (NEW or rename from AtomDetailCard)

---

### **Subtask 6: Update API Endpoint**

**Goal:** Backend returns Phase1AtomRow with PII data

**File:** `api/routes/batches.py` - GET `/api/v1/batches/{batch_id}/atoms/gate1`

**Changes:**
1. Query validated_atoms + flagged_atoms from state
2. For each atom, include PII entities from pii tracking
3. Return Phase1AtomRow[] with pii_detected and pii_entities

**No new endpoint needed** — reuse existing getGateAtoms() but extend response

---

## Implementation Order (Recommended)

### **Phase 1A: Backend Data Structure** (1-2 sessions)
1. ✅ Extend requirement.py: Add pii_entities field to ValidatedAtom/FlaggedAtom
2. ✅ Modify ingestion.py to track per-atom PII
3. ✅ Update batches.py to return pii_entities in response
4. ✅ Extend Phase1AtomRow TypeScript interface
5. ✅ Test with integration tests

### **Phase 1B: Basic UI Expansion** (1-2 sessions)
6. ✅ Add simple title tooltip for full requirement text
7. ✅ Implement click-to-expand row in PhaseGatePanel
8. ✅ Create RequirementPIIDetails component
9. ✅ Show PII in expanded row if detected

### **Phase 1C: Enhanced Details** (1-2 sessions)
10. ✅ Build Phase1AtomDetailCard drawer/modal
11. ✅ Integrate into table (click atom_id → open drawer)
12. ✅ Show original vs redacted text comparison

### **Phase 2: Guardrail Card Enhancement** (Optional, can defer)
13. ✅ Make PII count in GuardrailStatusCard expandable
14. ✅ Add jump-to-atom functionality

---

## Data Flow Diagram

```
Backend Flow:
═════════════
RawUpload
  ↓
Parse document → RequirementAtom[]
  ↓
redact_pii(text) → PIIRedactionResult {
  redacted_text: string
  entities_found: PIIEntity[]
  redaction_map: {placeholder → original}
}
  ↓
Attach entities to each atom: RequirementAtom.pii_entities = PIIEntity[]
  ↓
Quality gates → ValidatedAtom[] / FlaggedAtom[]
  ↓
Store in state: {
  validated_atoms: ValidatedAtom[]
  flagged_atoms: FlaggedAtom[]
  pii_redaction_map: {placeholder → original} // for Phase 5 CSV restore
}

Frontend Flow:
══════════════
GET /api/v1/batches/{id}/atoms/gate1
  ↓
Phase1AtomRow[] {
  atom_id, requirement_text, intent, module, priority,
  completeness_score, specificity_score,
  [NEW] pii_detected: bool,
  [NEW] pii_entities: PIIEntity[]
}
  ↓
PhaseGatePanel renders table:
  ├─ Requirement (click to expand)
  ├─ Intent
  ├─ Module
  ├─ Priority
  ├─ Completeness
  ├─ Specificity
  └─ [NEW] PII Status (show icon if detected)

User clicks row → RequirementDetailModal opens:
  ├─ Full requirement text
  ├─ All metadata
  ├─ RequirementPIIDetails (if pii_detected)
  │  ├─ Entity list with types
  │  ├─ Confidence scores
  │  └─ Original vs Redacted
  └─ Source file + page number
```

---

## Key Design Decisions

1. **PII Display Strategy:**
   - ✅ Show that PII was detected (yes/no indicator)
   - ✅ Show which entity types (not the actual sensitive data)
   - ✅ Show original vs redacted side-by-side in detail view only (not in table)
   - ❌ Never log or export the original PII in unredacted form

2. **Truncation Handling:**
   - ❌ Don't increase column width indefinitely (breaks table UX)
   - ✅ Use hover tooltip for quick preview
   - ✅ Use expandable rows or modals for full view

3. **Data Ownership:**
   - Backend owns PII metadata (what was detected)
   - Frontend owns UI presentation (how to show it)
   - Phase 5 owns PII restoration (final CSV output)

---

## Testing Strategy

### Backend Tests
- `test_ingestion_pii_detection.py`: Verify PIIEntity list attached to atoms
- `test_batches_gate1_response.py`: Verify Phase1AtomRow includes pii_entities
- Integration: Real PDF with PII → Check atoms have correct entity counts

### Frontend Tests
- Component: RequirementPIIDetails renders entity list correctly
- Component: PhaseGatePanel expands row with PII details
- Integration: Load gate1 → Click atom → Drawer opens with full details

---

## Security Considerations

⚠️ **Critical:**
- Never log or expose original PII in console/network
- Never send original PII to frontend EXCEPT in detail drawer (user-initiated)
- Placeholders only in public API responses
- Original values restored only at Phase 5 CSV output (final deliverable)

✅ **Implementation:**
- pii_entities sent to frontend: [{ entity_type, placeholder, score }, ...]
- original_text only in DetailCard component (requires user action)
- No pii data in logs (only counts and types logged)

---

## Success Criteria

### Subtask 1: Data Structure ✅
- [ ] ValidatedAtom has pii_entities field
- [ ] Phase1AtomRow has pii_detected, pii_entities
- [ ] Backend test passes with real PII example
- [ ] API returns correct pii data

### Subtask 2: Text Expansion ✅
- [ ] Requirement text fully visible on click
- [ ] Modal/drawer shows full atom details
- [ ] Source file and page number displayed
- [ ] No truncation in detail view

### Subtask 3: PII Details ✅
- [ ] PII entity list rendered correctly
- [ ] Entity types and scores visible
- [ ] Original vs redacted comparison shown
- [ ] Confidence scores formatted properly

### Subtask 4: Guardrail Card ✅
- [ ] PII count is clickable
- [ ] List of affected atom IDs shown
- [ ] Entity type summary visible
- [ ] Jump-to-atom functionality works

### Subtask 5: Detail Drawer ✅
- [ ] Opens on atom click or expand
- [ ] Shows all metadata (not just Requirement)
- [ ] PII details integrated
- [ ] Close button works, state managed

---

## Files to Create/Modify

### New Files
- `ui/src/components/progress/RequirementDetailModal.tsx`
- `ui/src/components/progress/RequirementPIIDetails.tsx`
- `ui/src/components/results/Phase1AtomDetailCard.tsx` (or rename existing)

### Modified Files
- `platform/schemas/requirement.py` — Add pii_entities to ValidatedAtom/FlaggedAtom
- `modules/dynafit/nodes/ingestion.py` — Track PII per atom
- `api/routes/batches.py` — Return pii_entities in gate response
- `ui/src/api/types.ts` — Extend Phase1AtomRow interface
- `ui/src/components/progress/PhaseGatePanel.tsx` — Add click-to-expand + PII badge
- `ui/src/components/progress/GuardrailStatusCard.tsx` — Make PII expandable (optional)

### No Changes Needed
- LLM client, retrieval, matching, classification, validation phases
- Phase 5 CSV output logic (pii_redaction_map already used there)
- WebSocket events

---

## Rollout Plan

**MVP (1-2 sprints):**
- Subtasks 1-3: Data + basic text expansion + PII details

**Phase 2 (Optional, can be deferred):**
- Subtasks 4-5: Enhanced guardrail card + detail drawer
