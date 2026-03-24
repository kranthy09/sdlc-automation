# Test Reduction & Consolidation Plan

**Target: Reduce test count by ~20%, shift from micro-unit to integration-first coverage**

> **Directive for Claude Code:** Follow this plan top-to-bottom. Each section tells you exactly which files to delete, which tests to remove from files, and which new integration tests to write. Do not deviate from the prescribed actions — this is a surgical reduction, not a rewrite.

---

## 0. Guiding Principle

The codebase currently tests _construction_ and _defaults_ — things Pydantic, Python, and the framework already guarantee. The goal is:

| Keep                                                                    | Delete                                                             |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Business rules (score ranges, routing thresholds, wave ≥ 1)             | Object instantiation / "can I build this" tests                    |
| Error paths (exception re-raise, rejection flow, status counters)       | Simple default value assertions                                    |
| Full pipeline journeys (upload → classify → report)                     | Every-enum-value coverage tests                                    |
| Golden fixture LLM replay                                               | Duplicate-pattern validations (same failure mode, different field) |
| Security guardrail contracts (injection block/flag, PII redact/restore) | Framework feature tests (Pydantic `frozen`, SQLAlchemy sessions)   |

**80% rule:** For every file below, keep only the tests that would catch a real regression in _business logic or platform contracts_. If a test only catches a typo in a constant, delete it.

---

## 1. Files to Delete Entirely

These files test infrastructure existence, import mechanics, or pure-framework behaviour. They add zero regression value once the scaffold is stable.

```
DELETE: tests/unit/test_scaffold.py
```

**Reason:** All three tests (`test_all_packages_importable`, `test_all_directories_exist`, `test_critical_files_exist`) verify that files exist on disk and that Python can import a package. These are CI infrastructure checks, not behaviour tests. If a package disappears, `make lint` (mypy strict) and every other test will fail first. This file is pure noise at this stage of the project.

**Claude Code action:**

```bash
rm tests/unit/test_scaffold.py
```

---

## 2. Files to Partially Prune

### 2a. `tests/unit/test_format_detector.py`

**Current tests (6):** PDF, DOCX, TXT detection + unknown binary, empty file, XLSX rejection.

**Keep (3):**

- `test_detects_pdf` — validates magic-byte branching logic, not obvious
- `test_detects_docx` — validates ZIP introspection logic
- `test_rejects_unknown_binary` — validates the error type and message shape

**Delete (3):**

- `test_detects_txt` — trivially: "file with no magic bytes and no zip → TXT". The negative of the other two; adds zero new branch coverage.
- `test_empty_file_raises` — duplicate of unknown-binary error path; same code branch, same exception type.
- `test_rejects_xlsx` — tests the _absence_ of DOCX internals in a ZIP. Same branch as unknown-binary rejection, different fixture.

**Claude Code action:** In `tests/unit/test_format_detector.py`, delete the test functions:

- `test_detects_txt`
- `test_empty_file_raises` (or equivalent empty-bytes test)
- `test_rejects_xlsx`

Leave the `_make_docx` and `_make_xlsx` helpers only if `_make_docx` is still referenced. Remove `_make_xlsx` helper if no remaining test uses it.

---

### 2b. `tests/unit/test_file_validator.py`

**Current tests (~9):** valid PDF, valid DOCX, valid TXT, unsupported binary, empty bytes, file-too-large, file-at-limit, SHA-256 hash accuracy, hash-present-on-rejection.

**Keep (5):**

- `test_valid_pdf` — confirms the happy-path returns `is_valid=True`, size, hash populated
- `test_rejects_binary_unknown` — confirms `unsupported_format:` rejection reason prefix
- `test_rejects_oversized_file` — confirms `file_too_large:` rejection reason prefix
- `test_hash_accuracy` — SHA-256 computation is custom logic; worth one assertion
- `test_hash_present_on_rejected_files` — audit-trail contract; security-relevant

**Delete (4):**

- `test_valid_docx` — same happy-path as `test_valid_pdf`; format detection covered in `test_format_detector.py`
- `test_valid_txt` — third repetition of the same happy path
- `test_empty_bytes_rejected` — subset of `test_rejects_binary_unknown`; same code path
- `test_file_exactly_at_limit` — boundary condition for a `>` vs `>=` operator. The only regression risk is changing that operator; covered by keeping the oversized test paired with a valid-size fixture in `test_valid_pdf`

**Claude Code action:** Delete the four functions listed above from `tests/unit/test_file_validator.py`.

---

### 2c. `tests/unit/test_api_dynafit.py`

**Current state:** This file has grown to cover individual field assertions per endpoint (e.g., `test_result_item_new_fields`, `test_review_item_new_fields`, `test_public_batches_filter_status`). Many are testing that a field is `None` — which is a default, not a behaviour.

**Keep (core contract tests):**

- Upload endpoint: one happy-path test confirming `batch_id` returned and status 202
- Status endpoint: one test confirming `status` field present
- Results endpoint: one test confirming `results` list shape (at least `atom_id`, `classification`)
- Review endpoint: one test confirming `items` list present for REVIEW_REQUIRED classification
- 404 for unknown batch — error contract

**Delete:**

- `test_result_item_new_fields` — asserts `config_steps is None`, `gap_description is None`, etc. These are default-value assertions, not behaviour. If the field changes, the schema test catches it.
- `test_review_item_new_fields` — same pattern: asserting specific field values (`dev_effort == "M"`) that belong in a module schema test, not an API contract test
- `test_public_batches_filter_status` — two sub-assertions (status=queued → empty, status=complete → 1). This is framework-level query filtering. Keep only `test_public_batches_listing`.

**Claude Code action:**
Delete these three test functions from `tests/unit/test_api_dynafit.py`:

- `test_result_item_new_fields`
- `test_review_item_new_fields`
- `test_public_batches_filter_status`

---

### 2d. `tests/unit/test_api_workers.py`

**Current tests:** `test_task_auto_resumes_no_hitl` and likely a few more covering the Celery task path.

**Keep (1):**

- `test_task_auto_resumes_no_hitl` — this tests a real business rule: when no `REVIEW_REQUIRED` items exist, Phase 5 runs automatically. This is observable, product-level behaviour.

**Delete (any of the following if they exist):**

- Any test that asserts `mock_vb.fit_count == 1` in isolation — the count is set by the mock, not by code under test
- Any test asserting that `asyncio.run` was called — this is internal implementation detail
- Any test that only checks `_emit` was called with no assertion on the payload shape

**Claude Code action:** Audit `tests/unit/test_api_workers.py`. Remove any test that is exclusively asserting mock call counts on infrastructure (not on business state transitions).

---

### 2e. `tests/integration/test_ingestion.py`

**Current tests (~11):** G1-lite rejection, G3-lite BLOCK, G3-lite FLAG, valid TXT pipeline, priority enrichment, specificity scoring, header column mapping, deduplication, quality gate, module-level smoke test, and possibly more.

**Keep (6) — these test non-trivial pipeline behaviour:**

- G1-lite: invalid file → rejection result (security contract)
- G3-lite BLOCK: injection at BLOCK level → pipeline halts (security contract)
- Valid TXT end-to-end: mocked LLM + embedder → `ValidatedAtom` list produced (core journey)
- Deduplication: near-identical atoms merged into one (algorithmic logic)
- Quality gate: vague atom → `FlaggedAtom`, not `ValidatedAtom` (classification contract)
- Module-level `ingestion_node` smoke: LangGraph state dict in → state dict out (integration boundary)

**Delete (5):**

- `test_g3_lite_flag` — the FLAG path is the _absence_ of a hard block. It's covered as a sub-assertion inside the valid TXT end-to-end test (errors list populated). Standalone test is redundant.
- `test_priority_enrichment` — tests that "must" keyword → `MUST` priority. This is a keyword lookup, not an algorithm. One assertion in the end-to-end test covers it.
- `test_specificity_scoring` — tests a scoring heuristic with vague vs specific text. The quality gate test already exercises the low-specificity path; this is a duplicate signal.
- `test_header_column_mapping` — exact and fuzzy header matching. This is table-parsing logic; belongs as one assertion in the end-to-end test, not a standalone test suite.
- G3-lite FLAG as standalone test (if separate from BLOCK test above)

**Claude Code action:** In `tests/integration/test_ingestion.py`:

1. Delete `test_g3_lite_flag_proceeds_with_errors` (or equivalent FLAG-level test)
2. Delete `test_priority_enrichment`
3. Delete `test_specificity_scoring`
4. Delete `test_header_column_mapping_exact` and `test_header_column_mapping_fuzzy` (or combined equivalent)
5. Verify the remaining end-to-end test (`test_valid_txt_pipeline`) includes at least one atom with a priority assertion so the enrichment logic is still exercised transitively.

---

### 2f. `tests/integration/test_phase3.py`

**Current tests:** matching node logic, FAST_TRACK routing, composite score, module-level smoke.

**Keep (2):**

- The FAST_TRACK routing test — this validates a scoring threshold gate, a real business rule
- `test_matching_node_function_accepts_state_dict` — integration boundary smoke test

**Delete:**

- Any test asserting a specific composite score value to 2 decimal places — exact floating-point scores are brittle and implementation-specific. Replace with a range assertion (`> 0.85`) if not already done. If the existing test already uses `>`, keep it as-is.
- Any test that sets up an identical fixture to the FAST_TRACK test but asserts a different route (e.g., a DEEP_DIVE route test) — consolidate into one parametrized test.

**Claude Code action:**

- If separate `test_deep_dive_route` and `test_fast_track_route` exist, consolidate into one `@pytest.mark.parametrize` test covering both routing outcomes with distinct fixture inputs.
- Delete any exact-score equality assertions (`assert mr.top_composite_score == 0.923`); replace with threshold assertions.

---

## 3. New Integration Tests to Write

These replace the deleted micro-tests with higher-value flow tests. Write these _after_ completing the deletions above.

### 3a. `tests/integration/test_dynafit_pipeline.py` _(new file)_

This is the **primary regression net** for the platform. It tests the full REQFIT journey end-to-end with mocked LLM and real schema validation.

```python
"""
REQFIT end-to-end pipeline integration test.

Covers: Phase 1 (ingestion) → Phase 2 (retrieval) → Phase 3 (matching)
        → Phase 4 (classification) → Phase 5 (validation + report)

Infrastructure: mocked LLM client, mocked embedder, in-memory vector store.
Docker NOT required. Mark: integration (because it exercises full graph).

Critical journeys:
  J1 — FIT classification: high-confidence requirement → FIT → appears in fitment matrix
  J2 — GAP classification: unrecognised requirement → GAP → flagged in matrix
  J3 — REVIEW_REQUIRED: medium-confidence → human review queue → override accepted
  J4 — Guardrail rejection: injection attempt → pipeline rejects before Phase 1 exits
"""
```

**Tests to implement:**

```
test_fit_journey_produces_fitment_matrix_entry()
  - Input: TXT file with one clearly-supported AP requirement
  - Mocks: LLM returns FIT + rationale, embedder returns high-cosine vector
  - Assert: ValidatedFitmentBatch.results[0].classification == "FIT"
  - Assert: report_path is not None (Excel generated)

test_gap_journey_flags_gap_in_matrix()
  - Input: TXT file with one custom/unsupported requirement
  - Mocks: LLM returns GAP, embedder returns low-cosine vector
  - Assert: classification == "GAP"
  - Assert: gap_description is not None

test_review_required_journey_enters_hitl_queue()
  - Input: TXT file with ambiguous requirement
  - Mocks: LLM returns REVIEW_REQUIRED + confidence = 0.55
  - Assert: batch review_count == 1
  - Assert: results[0].classification == "REVIEW_REQUIRED"

test_guardrail_injection_halts_pipeline()
  - Input: file bytes containing known injection pattern (BLOCK level)
  - Assert: returned state contains error entry, atoms list is empty
  - Assert: no LLM call was made (mock call_count == 0)
```

---

### 3b. `tests/integration/test_api_pipeline.py` _(new file)_

Tests the HTTP API surface as a pipeline, not individual routes. Uses `httpx.AsyncClient` against the real FastAPI app with mocked workers.

```
test_upload_to_results_happy_path()
  - POST /api/v1/d365_fo/dynafit/upload → 202, batch_id returned
  - GET  /api/v1/d365_fo/dynafit/{batch_id}/status → status in ["queued","processing","complete"]
  - Simulate task completion (patch worker)
  - GET  /api/v1/d365_fo/dynafit/{batch_id}/results → results list non-empty

test_upload_invalid_format_returns_400()
  - POST /api/v1/d365_fo/dynafit/upload with binary file
  - Assert 400, body contains "rejection_reason"

test_unknown_batch_returns_404()
  - GET /api/v1/d365_fo/dynafit/nonexistent-batch-id/results
  - Assert 404
```

---

## 4. conftest.py Cleanup

**File:** `tests/conftest.py`

No deletions needed. Add one shared fixture to support the new pipeline tests:

```python
@pytest.fixture
def mock_dynafit_graph():
    """
    Returns a pre-wired mock of the REQFIT LangGraph compiled graph.
    Patches platform.llm.client and platform.retrieval.embedder at fixture scope.
    All pipeline integration tests should use this fixture rather than
    individually patching LLM and embedder.
    """
    # Implementation: use platform.testing.factories.make_llm_client
    # and make_embedder — these already exist. Wire them here once.
    ...
```

This centralises the mock wiring so new pipeline tests get consistent infrastructure without re-implementing patch chains.

---

## 5. Execution Order for Claude Code

Execute strictly in this order to avoid breaking CI mid-migration:

```
Step 1: Delete tests/unit/test_scaffold.py
Step 2: Prune tests/unit/test_format_detector.py (remove 3 tests)
Step 3: Prune tests/unit/test_file_validator.py (remove 4 tests)
Step 4: Prune tests/unit/test_api_dynafit.py (remove 3 tests)
Step 5: Prune tests/unit/test_api_workers.py (remove mock-count-only tests)
Step 6: Prune tests/integration/test_ingestion.py (remove 5 tests)
Step 7: Consolidate tests/integration/test_phase3.py (parametrize routing tests)
Step 8: Run: make test — CI must be GREEN before proceeding
Step 9: Add mock_dynafit_graph fixture to tests/conftest.py
Step 10: Write tests/integration/test_dynafit_pipeline.py (4 journey tests)
Step 11: Write tests/integration/test_api_pipeline.py (3 journey tests)
Step 12: Run: make test — CI must be GREEN
Step 13: Run: make lint — zero errors required
```

---

## 6. Expected Before / After

| Metric                                    | Before | After                                      |
| ----------------------------------------- | ------ | ------------------------------------------ |
| Total test functions (approx)             | ~55    | ~38                                        |
| Unit tests                                | ~38    | ~22                                        |
| Integration tests                         | ~17    | ~16 (+7 new journey tests, -8 micro tests) |
| Tests covering full pipeline journeys     | 0      | 7                                          |
| Tests asserting only defaults/None values | ~8     | 0                                          |
| Tests asserting mock call counts only     | ~3     | 0                                          |

---

## 7. What NOT to Touch

These tests are correctly scoped and must not be modified:

- `tests/unit/test_api_workers.py::test_task_auto_resumes_no_hitl` — real business rule
- `tests/integration/test_ingestion.py` G1-lite and G3-lite BLOCK tests — security contracts
- `tests/integration/test_phase3.py` FAST_TRACK routing test — threshold gate logic
- All `@pytest.mark.golden` fixture tests — LLM replay tests are always worth keeping
- `tests/conftest.py` marker registrations — do not remove any `addinivalue_line` calls

---

## 8. CI Gate Verification

After completing all steps, verify these three gates pass:

```bash
make lint                # ruff + mypy --strict — zero errors
make test                # pytest --cov — all tests green, coverage ≥ prior baseline
make validate-contracts  # import boundary + manifest — zero violations
```

Coverage may _increase_ slightly despite fewer tests because the new pipeline journey tests exercise more code paths per test than the deleted micro-tests did.
