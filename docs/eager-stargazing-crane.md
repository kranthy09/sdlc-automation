# DYNAFIT Validation & MVP Gap-Fill Plan

## Context

The DYNAFIT Module 1 implementation is architecturally complete across all 5 phases and the full API/UI stack (Layer 4). However, three blocking gaps prevent the business logic from executing correctly end-to-end:

1. **graph.py wires the Phase 5 stub** — the real `ValidationNode` in `phase5_validation.py` is never called; every batch ends with `validated_batch=None`
2. **Qdrant has no data** — `knowledge_bases/` directory doesn't exist; Phase 2 returns 0 capabilities; Phase 4 short-circuits every requirement to GAP via the "no capabilities → auto-GAP" path
3. **Seed script doesn't exist** — `make seed-kb` references `infra.scripts.seed_knowledge_base` which was never created

Secondary gaps: `modules/dynafit/tests/` is empty (make test-module M=dynafit passes vacuously), and one existing graph test asserts stub behavior that breaks after the Phase 5 fix.

**Intended outcome:** Upload a 10-requirement DOCX/TXT, run the pipeline, get FIT/PARTIAL_FIT/GAP classifications with real LLM reasoning against real D365 F&O capabilities, HITL fires for low-confidence items, Phase 5 writes CSV reports.

---

## Task 1 — Fix graph.py: Wire Real Phase 5 [CRITICAL]

**File:** `modules/dynafit/graph.py:42`

**Change one import line:**
```python
# Before (stub — returns validated_batch=None always):
from .nodes.validation import validation_node

# After (real — HITL + CSV output + postgres write-back):
from .nodes.phase5_validation import validation_node
```

`phase5_validation.py:565` already exports a module-level `validation_node` function (singleton pattern identical to classification.py). No other changes needed in graph.py.

**Broken test to fix — `tests/integration/test_dynafit_graph.py:79-103`**

`test_stub_resume_completes_phase5` asserts `final_state["validated_batch"] is None` (stub behavior). After the fix, real Phase 5 runs and needs postgres + redis.

Update the test:
- Monkeypatch `modules.dynafit.nodes.phase5_validation._node` with a `ValidationNode` instance that has injected mocks: `make_postgres_store()`, `make_redis_pub_sub()`, `make_embedder()`, `report_dir=tmp_path`
- Assert `final_state["validated_batch"]` is a `ValidatedFitmentBatch` with `total_atoms=0` (empty input from stub phases)
- Update comment on line 101 to remove "stub" language

---

## Task 2 — Create Lite Knowledge Base Data [30-min setup]

### Files to create

**`knowledge_bases/d365_fo/capabilities_lite.yaml`** — 60 capabilities, 10 per module

Format:
```yaml
capabilities:
  - id: cap-ap-0001
    module: AccountsPayable
    feature: Three-way Matching
    description: >
      D365 F&O supports automated three-way matching between purchase orders,
      product receipts, and vendor invoices. Quantities and prices are validated
      against configurable tolerance thresholds per vendor group. Mismatches are
      flagged for AP clerk review before payment release.
```

Modules and features (10 each):

| Module | cap IDs | Features |
|--------|---------|----------|
| AccountsPayable | cap-ap-0001–0010 | Three-way matching, Invoice automation (OCR), Payment proposal, Vendor hold management, Vendor self-service portal, Early payment discount (2/10 net 30), AP aging report, Invoice matching policy (2-way/3-way), MICR check printing, ACH/wire electronic payments |
| AccountsReceivable | cap-ar-0001–0010 | Customer credit limit management, Dunning letter automation, Cash application (auto-match), AR aging analysis, Collections management workflow, Electronic customer invoicing, Recurring billing schedules, Revenue recognition (ASC 606 / IFRS 15), Write-off workflow, Interest notes for overdue accounts |
| GeneralLedger | cap-gl-0001–0010 | Period close management (tasks + calendar), Financial report designer (row/column/tree), Intercompany accounting (elimination), Dimension-based allocation rules, Budget control (commitments + actuals), Trial balance report, Multi-currency revaluation (realized/unrealized), Legal entity consolidation, Audit trail (user/date/field), Bank reconciliation |
| InventoryManagement | cap-inv-0001–0010 | FIFO/LIFO/Weighted Average costing, Inventory adjustment journals, Physical inventory counting (cycle count), Batch number tracking, Serial number tracking, Item model group (costing method), Inventory valuation report, Quality orders (inspection), Landed cost distribution, Goods-in-transit accounting |
| ProcurementSourcing | cap-proc-0001–0010 | PO approval workflow (approval hierarchy), Vendor catalog (punchout + internal), Purchase agreement (blanket PO), Vendor evaluation scorecard, Purchase requisition with budget check, Direct delivery (PO → customer), Request for quotation (RFQ/RFP), Procurement policy engine, Spend analysis dashboard, Supplier collaboration portal |
| ProjectManagement | cap-proj-0001–0010 | Work breakdown structure (WBS), Resource assignment and capacity, Timesheet approval workflow, Expense report and policy enforcement, Project invoicing (T&M + fixed price), WIP accounting (revenue recognition), Milestone-based billing, Project budget and forecast, Earned value analysis (CPI/SPI), Intercompany project billing |

**`knowledge_bases/d365_fo/country_rules/global.yaml`** — placeholder (empty rules list):
```yaml
# Country rules — global (no overrides)
# Country-specific files: de.yaml, us.yaml, gb.yaml (future)
rules: []
```

**`knowledge_bases/d365_fo/fdd_templates/fit_template.j2`** — minimal Jinja2 template:
```jinja2
{# FDD fit template — used by Phase 5 report generation #}
{{ feature }} — {{ classification }} ({{ "%.0f"|format(confidence * 100) }}% confidence)
```

---

## Task 3 — Create Seeding Script

**New file:** `infra/scripts/seed_knowledge_base.py`

CLI: `python -m infra.scripts.seed_knowledge_base --product d365_fo [--source lite|full] [--reset]`

Implementation steps:
1. Parse args: `--product` (required), `--source` (default `lite`), `--reset` (drop+recreate collection)
2. Load `knowledge_bases/{product}/capabilities_lite.yaml` → list of capability dicts
3. Init `Embedder(settings.embedding_model)` — lazy load BAAI/bge-small-en-v1.5
4. Init `BM25Retriever()` — fit on all capability descriptions for IDF weighting
5. Init `VectorStore(settings.qdrant_url)` — connect to Qdrant
6. Create/ensure collection `{product}_capabilities`:
   - `vector_size=384`, `distance="cosine"`, `sparse=True`
7. Batch-embed all descriptions via `embedder.embed_batch(texts)`
8. For each capability build `Point(id=cap.id, dense_vector=..., payload={module, feature, description}, sparse=bm25.encode(text))`
9. Upsert all points via `vector_store.upsert(collection, points)`
10. Print: `Seeded {N} capabilities to '{collection}' in Qdrant at {url}`

**Reuse from platform:**
- `platform.retrieval.embedder.Embedder` (`platform/retrieval/embedder.py`)
- `platform.retrieval.bm25.BM25Retriever` (`platform/retrieval/bm25.py`)
- `platform.retrieval.vector_store.VectorStore` (`platform/retrieval/vector_store.py`)
- `platform.config.settings.get_settings()` (`platform/config/settings.py`)

**Add to Makefile** (after existing `seed-kb` target):
```makefile
seed-kb-lite:
	uv run python -m infra.scripts.seed_knowledge_base --product d365_fo --source lite
```

---

## Task 4 — Phase 3 Pure Unit Tests (satisfies `make test-module M=dynafit`)

**New file:** `modules/dynafit/tests/test_phase3_pure.py`

Import targets (all pure functions, no infra):
- `modules.dynafit.nodes.matching._compute_composite` (line 69)
- `modules.dynafit.nodes.matching._assign_route` (line 74)
- `modules.dynafit.nodes.matching._detect_anomaly` (line 83)
- `modules.dynafit.nodes.matching._entity_overlap_score` (line 97)

Tests (all `@pytest.mark.unit`):
1. `test_composite_all_ones` — all 5 signals = 1.0 → composite = 1.0
2. `test_composite_weighted` — known values → expected weighted sum (0.25+0.20+0.15+0.25+0.15)
3. `test_composite_history_boost_caps_at_one` — composite 0.95 + history boost → ≤ 1.0
4. `test_assign_route_fast_track` — composite 0.90, has_history=True → FAST_TRACK
5. `test_assign_route_deep_reason` — composite 0.72, has_history=False → DEEP_REASON
6. `test_assign_route_gap_confirm` — composite 0.45 → GAP_CONFIRM
7. `test_anomaly_fires_high_cosine_low_entity` — cosine 0.87, entity_overlap 0.15 → True
8. `test_anomaly_no_fire_high_entity` — cosine 0.87, entity_overlap 0.25 → False
9. `test_anomaly_no_fire_low_cosine` — cosine 0.80, entity_overlap 0.10 → False
10. `test_entity_overlap_exact_match` — hint in description → score > 0
11. `test_entity_overlap_no_hints` — empty hints → 0.0

**New file:** `modules/dynafit/tests/test_guardrails.py`

Import: `modules.dynafit.guardrails.run_sanity_check`

Tests (all `@pytest.mark.unit`):
1. `test_high_confidence_gap_flagged` — confidence > 0.85, GAP → flags present
2. `test_low_score_fit_flagged` — composite < 0.60, FIT → flags present
3. `test_llm_retry_exhausted_flagged` — route REVIEW_REQUIRED → flags present
4. `test_clean_fit_no_flags` — FIT, confidence 0.92, composite 0.88 → empty flags

---

## Task 5 — Sample Requirements Fixture + Smoke Test

**New file:** `tests/fixtures/sample_requirements.txt`

10 requirements for US AccountsPayable + AccountsReceivable wave (Wave 1):
- REQ-001: Three-way matching AP (→ FIT expected, cap-ap-0001)
- REQ-002: Early payment discount auto-calculation (→ FIT, cap-ap-0006)
- REQ-003: Vendor self-service portal for invoice status (→ FIT, cap-ap-0005)
- REQ-004: AR dunning letters with configurable frequency (→ FIT, cap-ar-0002)
- REQ-005: Cash auto-application against customer remittances (→ FIT, cap-ar-0003)
- REQ-006: Customer credit limit enforcement at order entry (→ FIT, cap-ar-0001)
- REQ-007: AP aging by vendor with drill-down to invoices (→ FIT, cap-ap-0007)
- REQ-008: The system should handle data. (→ FLAGGED by quality gate, specificity < 0.30)
- REQ-009: Revenue recognition for multi-element arrangements per ASC 606 (→ PARTIAL_FIT or FIT, cap-ar-0008)
- REQ-010: Three-way matching between PO, receipt, and vendor invoice (→ deduped with REQ-001)

**New file:** `infra/scripts/smoke_test.py`

CLI: `python -m infra.scripts.smoke_test [--file tests/fixtures/sample_requirements.txt] [--country US] [--wave 1]`

Steps:
1. Read file → `RawUpload(product_id="d365_fo", country="US", wave=1, ...)`
2. `graph = build_dynafit_graph(checkpointer=MemorySaver())`
3. `state = graph.invoke({upload, batch_id, errors: []}, config)` — runs phases 1–4
4. Check `state.get("classifications", [])` for REVIEW_REQUIRED items
5. If HITL needed: auto-approve all (overrides = {atom_id: None for each}) → resume
6. If no HITL: resume directly for Phase 5
7. `final = graph.invoke(None, config)` — runs Phase 5
8. Print table: `atom_id | text[:60] | classification | confidence | rationale[:80]`
9. Print summary: atoms produced, dedup removed, flagged by quality gate, FIT/PARTIAL/GAP counts

Note: `ValidationNode` singleton will use real postgres + redis. Script expects `make services` to be running. For offline testing, pass `--mock-infra` flag to inject mock postgres/redis.

**Add to Makefile:**
```makefile
smoke-test:
	uv run python -m infra.scripts.smoke_test
```

---

## Execution Order

```
Step 1:  Fix graph.py (1 line)                              → make test-unit passes
Step 2:  Fix test_dynafit_graph.py (test_stub_resume_*)     → make test-unit still passes
Step 3:  Create knowledge_bases/ files (YAML + templates)   → no runtime impact yet
Step 4:  Create infra/scripts/seed_knowledge_base.py        → make seed-kb-lite works
Step 5:  Create modules/dynafit/tests/ pure unit tests      → make test-module M=dynafit passes
Step 6:  Create tests/fixtures/sample_requirements.txt      → smoke test input ready
Step 7:  Create infra/scripts/smoke_test.py                 → make smoke-test works
```

## Verification

```bash
# 1. Start backing services (Qdrant :6333, Postgres :5432, Redis :6379)
make services

# 2. Populate Qdrant with 60 capabilities (~3–5 min for first embed)
make seed-kb-lite

# 3. All unit tests pass (no Docker required)
make test-unit

# 4. Module-specific pure unit tests pass
make test-module M=dynafit

# 5. Integration tests pass (requires Docker services)
make test-integration

# 6. End-to-end pipeline smoke test (requires ANTHROPIC_API_KEY + running services)
ANTHROPIC_API_KEY=... make smoke-test
# Expected: ≥9 atoms (REQ-010 deduped), REQ-008 flagged as quality gate,
#           5–7 FIT, 1–2 PARTIAL_FIT, 0–1 GAP, CSV reports written to reports/

# 7. API smoke test
make test-api

# 8. Full CI gate
make ci
```

## Critical Files Modified

| File | Change | Why |
|------|--------|-----|
| `modules/dynafit/graph.py:42` | Fix import | Wire real Phase 5 |
| `tests/integration/test_dynafit_graph.py:79-103` | Update test | Adapts to real Phase 5 behavior |
| `knowledge_bases/d365_fo/capabilities_lite.yaml` | New | RAG data for Phase 2 |
| `knowledge_bases/d365_fo/country_rules/global.yaml` | New | Config path placeholder |
| `knowledge_bases/d365_fo/fdd_templates/fit_template.j2` | New | Config path placeholder |
| `infra/scripts/seed_knowledge_base.py` | New | Populate Qdrant in <30 min |
| `modules/dynafit/tests/test_phase3_pure.py` | New | Pure unit tests, no infra |
| `modules/dynafit/tests/test_guardrails.py` | New | G10-lite sanity gate tests |
| `tests/fixtures/sample_requirements.txt` | New | Smoke test input |
| `infra/scripts/smoke_test.py` | New | E2E validation script |
| `Makefile` | Add 2 targets | `seed-kb-lite`, `smoke-test` |
