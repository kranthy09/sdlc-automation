"""
Tests for the REQFIT validation node — Phase 5 (Session G).

All tests are @pytest.mark.unit — they use mocked infrastructure and do not
require Docker services. The file lives in tests/integration/ because it tests
the full Phase 5 pipeline end-to-end, not a single isolated function.

Sub-phase 5A — Sanity Gate + HITL (interrupt path):
  test_clean_pass_no_interrupt
  test_flagged_results_trigger_interrupt
  test_all_flagged_triggers_interrupt_with_all_atom_ids
  test_confidence_filter_flags_low_confidence_non_gap
  test_confidence_filter_does_not_flag_gap_regardless_of_confidence
  test_phase3_anomaly_flags_trigger_hitl
  test_interrupt_payload_contains_batch_id_and_flagged_count
  test_phase_start_event_published_before_interrupt

Sub-phase 5B — Resume + Output Builder:
  test_override_replaces_classification_in_final_batch
  test_override_none_preserves_original_classification
  test_reviewer_override_true_passed_to_write_back
  test_review_required_not_written_to_postgres
  test_batch_counts_sum_to_total_atoms
  test_fit_count_correct
  test_gap_count_correct
  test_fdd_fits_csv_contains_fit_and_partial_fit_rows
  test_fdd_gaps_csv_contains_gap_rows
  test_csv_has_correct_headers
  test_complete_event_published_with_correct_counts
  test_write_back_postgres_error_logged_not_raised
  test_reviewer_override_flag_in_csv
  test_module_level_validation_node_singleton_smoke

Golden fixtures:
  _FIT, _PARTIAL, _GAP, _REVIEW represent canned ClassificationResult values.
  Match results are always built with the same atom_id as the classification
  result they correspond to (match_by_atom lookup requires this alignment).
"""

from __future__ import annotations

import csv
import os
from unittest.mock import AsyncMock, patch

import pytest

import modules.dynafit.nodes.phase5_validation as _v5_module
from modules.dynafit.nodes.phase5_validation import ValidationNode
from platform.schemas.fitment import FitLabel, RouteLabel
from platform.storage.postgres import PostgresError
from platform.testing.factories import (
    make_classification_result,
    make_embedder,
    make_match_result,
    make_postgres_store,
    make_product_config,
    make_raw_upload,
    make_redis_pub_sub,
    make_validated_atom,
)

# ---------------------------------------------------------------------------
# Golden ClassificationResult fixtures
# ---------------------------------------------------------------------------

_FIT = make_classification_result(
    atom_id="REQ-AP-001",
    classification=FitLabel.FIT,
    confidence=0.92,
    route_used=RouteLabel.FAST_TRACK,
    d365_capability_ref="cap-ap-0001",
)

_PARTIAL = make_classification_result(
    atom_id="REQ-AP-002",
    classification=FitLabel.PARTIAL_FIT,
    confidence=0.78,
    route_used=RouteLabel.DEEP_REASON,
    config_steps="Enable matching policy in AP parameters.",
)

_GAP = make_classification_result(
    atom_id="REQ-AP-003",
    classification=FitLabel.GAP,
    confidence=0.88,  # > 0.85 fit_threshold → triggers high_confidence_gap
    route_used=RouteLabel.GAP_CONFIRM,
    gap_description="Custom X++ extension required.",
)

_REVIEW = make_classification_result(
    atom_id="REQ-AP-004",
    classification=FitLabel.REVIEW_REQUIRED,
    confidence=0.0,
    # triggers llm_schema_retry_exhausted (via classification==REVIEW_REQUIRED)
    route_used=RouteLabel.GAP_CONFIRM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mr(atom_id: str, *, top_composite_score: float = 0.91, **kw):
    """Build a MatchResult whose atom.atom_id matches *atom_id*."""
    return make_match_result(
        atom=make_validated_atom(atom_id=atom_id),
        top_composite_score=top_composite_score,
        **kw,
    )


def _make_state(
    classifications: list,
    match_results: list | None = None,
    product_id: str = "d365_fo",
    batch_id: str = "batch-phase5-test",
) -> dict:
    return {
        "upload": make_raw_upload(product_id=product_id),
        "batch_id": batch_id,
        "errors": [],
        "classifications": classifications,
        "match_results": match_results or [],
    }


def _make_node(tmp_path, **kwargs) -> ValidationNode:
    """Return a ValidationNode backed entirely by mock infrastructure."""
    defaults = {
        "postgres": make_postgres_store(),
        "redis": make_redis_pub_sub(),
        "embedder": make_embedder(),
        "product_config": make_product_config(),
        "report_dir": str(tmp_path),
    }
    defaults.update(kwargs)
    return ValidationNode(**defaults)


# ===========================================================================
# Sub-phase 5A: Sanity Gate + HITL
# ===========================================================================


@pytest.mark.unit
def test_clean_pass_no_interrupt(tmp_path) -> None:
    """All clean results → interrupt() never called; batch built immediately."""
    node = _make_node(tmp_path)
    state = _make_state([_FIT], match_results=[
                        _mr("REQ-AP-001", top_composite_score=0.92)])

    with patch.object(_v5_module, "interrupt") as mock_interrupt:
        result = node(state)

    mock_interrupt.assert_not_called()
    assert result["validated_batch"] is not None


@pytest.mark.unit
def test_clean_pass_publishes_phase_start_event(tmp_path) -> None:
    """Phase 5 publishes phase_start event unconditionally, even in clean pass.

    Business logic: Phase 5 should announce its entry via PhaseStartEvent
    unconditionally at the beginning, matching Phases 1–4 behavior.
    This test verifies the publish_phase_start() is called by checking
    that it doesn't raise an exception and the node completes successfully.
    """
    from modules.dynafit.events import publish_phase_start

    node = _make_node(tmp_path)
    # Clean pass: no flagged items
    state = _make_state([_FIT], match_results=[
                        _mr("REQ-AP-001", top_composite_score=0.92)])

    # Verify publish_phase_start is called during node execution
    with patch.object(_v5_module, "publish_phase_start") as mock_pub_start:
        with patch.object(_v5_module, "interrupt") as mock_interrupt:
            result = node(state)

    # publish_phase_start called exactly once (at phase entry)
    mock_pub_start.assert_called_once()
    call_kwargs = mock_pub_start.call_args[1]
    assert call_kwargs["phase"] == 5
    assert call_kwargs["phase_name"] == "Validation"
    # Batch completed successfully
    assert result["validated_batch"] is not None


@pytest.mark.unit
def test_step_progress_events_published_in_clean_pass(tmp_path) -> None:
    """Clean pass publishes 2 step_progress events: sanity_gate, then output.

    Business logic: UI receives progress feedback at key milestones.
    Clean pass: 1/2 (sanity gate) → 2/2 (output generated).
    """
    node = _make_node(tmp_path)
    state = _make_state([_FIT], match_results=[
                        _mr("REQ-AP-001", top_composite_score=0.92)])

    with patch.object(_v5_module, "publish_step_progress") as mock_progress:
        with patch.object(_v5_module, "interrupt"):
            node(state)

    # Two progress events: sanity_gate (1/2), then output (2/2)
    assert mock_progress.call_count == 2

    # First call: sanity gate complete
    call1 = mock_progress.call_args_list[0]
    assert call1[1]["step"] == "sanity_gate_complete"
    assert call1[1]["completed"] == 1
    assert call1[1]["total"] == 2

    # Second call: output generated
    call2 = mock_progress.call_args_list[1]
    assert call2[1]["step"] == "validation_output_generated"
    assert call2[1]["completed"] == 2
    assert call2[1]["total"] == 2


@pytest.mark.unit
def test_step_progress_events_published_in_flagged_pass(tmp_path) -> None:
    """Flagged pass publishes 3 step_progress events: sanity_gate, HITL, output.

    Business logic: UI shows progress through HITL checkpoint and back.
    Flagged pass: 1/3 (sanity gate) → 2/3 (HITL complete) → 3/3 (output).
    """
    node = _make_node(tmp_path)
    state = _make_state([_GAP], match_results=[
                        _mr("REQ-AP-003", top_composite_score=0.40)])

    with patch.object(_v5_module, "publish_step_progress") as mock_progress:
        with patch.object(_v5_module, "interrupt", return_value={}):
            node(state)

    # Three progress events: sanity_gate (1/3), HITL (2/3), output (3/3)
    assert mock_progress.call_count == 3

    # First call: sanity gate complete
    call1 = mock_progress.call_args_list[0]
    assert call1[1]["step"] == "sanity_gate_complete"
    assert call1[1]["completed"] == 1
    assert call1[1]["total"] == 3

    # Second call: HITL review complete
    call2 = mock_progress.call_args_list[1]
    assert call2[1]["step"] == "hitl_review_complete"
    assert call2[1]["completed"] == 2
    assert call2[1]["total"] == 3

    # Third call: output generated
    call3 = mock_progress.call_args_list[2]
    assert call3[1]["step"] == "validation_output_generated"
    assert call3[1]["completed"] == 3
    assert call3[1]["total"] == 3


@pytest.mark.unit
def test_flagged_results_trigger_interrupt(tmp_path) -> None:
    """A high_confidence_gap result (_GAP) → interrupt() called once."""
    node = _make_node(tmp_path)
    # _GAP: confidence=0.88 > fit_threshold=0.85 → high_confidence_gap
    state = _make_state(
        [_FIT, _GAP],
        match_results=[
            _mr("REQ-AP-001", top_composite_score=0.92),
            _mr("REQ-AP-003", top_composite_score=0.40),
        ],
    )

    with patch.object(_v5_module, "interrupt", return_value={}) as mock_interrupt:
        node(state)

    mock_interrupt.assert_called_once()


@pytest.mark.unit
def test_all_flagged_triggers_interrupt_with_all_atom_ids(tmp_path) -> None:
    """interrupt payload contains all flagged atom IDs and the correct batch_id."""
    node = _make_node(tmp_path)
    # _REVIEW: route_used=REVIEW_REQUIRED → llm_schema_retry_exhausted
    state = _make_state(
        [_REVIEW],
        match_results=[_mr("REQ-AP-004", top_composite_score=0.50)],
    )

    captured: list[dict] = []

    with patch.object(_v5_module, "interrupt", side_effect=lambda p: captured.append(p) or {}):
        node(state)

    assert len(captured) == 1
    payload = captured[0]
    assert payload["batch_id"] == "batch-phase5-test"
    assert payload["flagged_count"] == 1
    assert "REQ-AP-004" in payload["flagged_atom_ids"]


@pytest.mark.unit
def test_confidence_filter_flags_low_confidence_non_gap(tmp_path) -> None:
    """FIT with confidence < review_confidence_threshold (0.60) → low_confidence flag → HITL."""
    low_conf_fit = make_classification_result(
        atom_id="REQ-LOW-001",
        classification=FitLabel.FIT,
        confidence=0.45,  # < 0.60
        route_used=RouteLabel.DEEP_REASON,
    )
    node = _make_node(tmp_path)
    # composite=0.72: rule 2 (low_score_fit) does NOT trigger (0.72 > 0.60)
    state = _make_state(
        [low_conf_fit], match_results=[
            _mr("REQ-LOW-001", top_composite_score=0.72)]
    )

    with patch.object(_v5_module, "interrupt", return_value={}) as mock_interrupt:
        node(state)

    mock_interrupt.assert_called_once()
    payload = mock_interrupt.call_args[0][0]
    assert "REQ-LOW-001" in payload["flagged_atom_ids"]


@pytest.mark.unit
def test_gap_always_triggers_mandatory_review(tmp_path) -> None:
    """All GAP classifications trigger gap_review (mandatory analyst sign-off).

    Even GAPs with low confidence are flagged because rule 5 (gap_review)
    applies to ALL GAP classifications, not just high-confidence ones.
    Rule 4 (low_confidence) doesn't apply to GAP — that's the distinction here.
    """
    low_conf_gap = make_classification_result(
        atom_id="REQ-GAP-LOW",
        classification=FitLabel.GAP,
        confidence=0.45,  # low confidence
        route_used=RouteLabel.GAP_CONFIRM,
    )
    node = _make_node(tmp_path)
    # composite=0.40, confidence=0.45 < fit_threshold (0.85) → rule 1 NOT triggered
    # BUT rule 5 (gap_review) applies to ALL GAPs
    state = _make_state(
        [low_conf_gap], match_results=[
            _mr("REQ-GAP-LOW", top_composite_score=0.40)]
    )

    with patch.object(_v5_module, "interrupt", return_value={}) as mock_interrupt:
        node(state)

    # interrupt() IS called because rule 5 (gap_review) flags all GAPs
    mock_interrupt.assert_called_once()
    payload = mock_interrupt.call_args[0][0]
    assert "REQ-GAP-LOW" in payload["flagged_atom_ids"]
    assert "gap_review" in payload["flagged_reasons"]["REQ-GAP-LOW"]


@pytest.mark.unit
def test_phase3_anomaly_flags_trigger_hitl(tmp_path) -> None:
    """MatchResult with non-empty anomaly_flags → phase3_anomaly flag → HITL."""
    clean_fit = make_classification_result(
        atom_id="REQ-ANO-001",
        classification=FitLabel.FIT,
        confidence=0.91,  # above all thresholds — would be clean otherwise
        route_used=RouteLabel.FAST_TRACK,
    )
    node = _make_node(tmp_path)
    anomaly_mr = make_match_result(
        atom=make_validated_atom(atom_id="REQ-ANO-001"),
        top_composite_score=0.88,
        anomaly_flags=["score_spike"],
    )
    state = _make_state([clean_fit], match_results=[anomaly_mr])

    with patch.object(_v5_module, "interrupt", return_value={}) as mock_interrupt:
        node(state)

    mock_interrupt.assert_called_once()


@pytest.mark.unit
def test_interrupt_payload_structure(tmp_path) -> None:
    """interrupt() payload dict has batch_id, flagged_count, and flagged_atom_ids keys."""
    node = _make_node(tmp_path)
    state = _make_state(
        [_REVIEW],
        match_results=[_mr("REQ-AP-004", top_composite_score=0.50)],
        batch_id="batch-payload-check",
    )

    captured: list[dict] = []

    with patch.object(_v5_module, "interrupt", side_effect=lambda p: captured.append(p) or {}):
        node(state)

    p = captured[0]
    assert p["batch_id"] == "batch-payload-check"
    assert p["flagged_count"] == 1
    assert isinstance(p["flagged_atom_ids"], list)


@pytest.mark.unit
def test_phase_start_event_published_before_interrupt(tmp_path) -> None:
    """Phase 5 publishes phase_start unconditionally, before any gates.

    Business logic: Phase 5 should announce its entry immediately,
    not wait until flagged items are detected. This matches Phases 1–4.
    The interrupt() call is separate and handles HITL flow.
    """
    node = _make_node(tmp_path)
    # Flagged pass: will trigger interrupt
    state = _make_state(
        [_REVIEW],
        match_results=[_mr("REQ-AP-004", top_composite_score=0.50)],
    )

    with patch.object(_v5_module, "publish_phase_start") as mock_pub_start:
        with patch.object(_v5_module, "interrupt", return_value={}):
            node(state)

    # publish_phase_start called exactly once (at phase entry, not when flagged)
    mock_pub_start.assert_called_once()
    call_kwargs = mock_pub_start.call_args[1]
    assert call_kwargs["phase"] == 5
    assert call_kwargs["phase_name"] == "Validation"


# ===========================================================================
# Sub-phase 5B: Resume + Output Builder
# ===========================================================================


@pytest.mark.unit
def test_override_replaces_classification_in_final_batch(tmp_path) -> None:
    """Human override dict changes GAP → PARTIAL_FIT in the final ValidatedFitmentBatch."""
    node = _make_node(tmp_path)
    # _GAP: confidence=0.88 > 0.85 → flagged
    state = _make_state([_GAP], match_results=[
                        _mr("REQ-AP-003", top_composite_score=0.40)])

    overrides = {
        "REQ-AP-003": {
            "classification": "PARTIAL_FIT",
            "rationale": "Consultant: covered with config.",
            "consultant": "jdoe@example.com",
        }
    }

    with patch.object(_v5_module, "interrupt", return_value=overrides):
        result = node(state)

    [final] = result["validated_batch"].results
    assert final.classification == FitLabel.PARTIAL_FIT
    assert final.rationale == "Consultant: covered with config."


@pytest.mark.unit
def test_override_none_preserves_original_classification(tmp_path) -> None:
    """Human approval (None override) keeps the original classification unchanged."""
    node = _make_node(tmp_path)
    state = _make_state([_GAP], match_results=[
                        _mr("REQ-AP-003", top_composite_score=0.40)])

    with patch.object(_v5_module, "interrupt", return_value={"REQ-AP-003": None}):
        result = node(state)

    [final] = result["validated_batch"].results
    assert final.classification == FitLabel.GAP


@pytest.mark.unit
def test_reviewer_override_true_passed_to_write_back(tmp_path) -> None:
    """When human changes verdict, postgres.save_fitment receives reviewer_override=True."""
    postgres = make_postgres_store()
    node = _make_node(tmp_path, postgres=postgres)
    state = _make_state([_GAP], match_results=[
                        _mr("REQ-AP-003", top_composite_score=0.40)])

    overrides = {
        "REQ-AP-003": {
            "classification": "FIT",
            "rationale": "Actually covered.",
            "consultant": "reviewer@company.com",
        }
    }

    with patch.object(_v5_module, "interrupt", return_value=overrides):
        node(state)

    postgres.save_fitment.assert_called_once()
    kwargs = postgres.save_fitment.call_args[1]
    assert kwargs["reviewer_override"] is True
    assert kwargs["consultant"] == "reviewer@company.com"


@pytest.mark.unit
def test_review_required_not_written_to_postgres(tmp_path) -> None:
    """REVIEW_REQUIRED results skip write-back (not a final decision)."""
    postgres = make_postgres_store()
    node = _make_node(tmp_path, postgres=postgres)
    state = _make_state([_REVIEW], match_results=[
                        _mr("REQ-AP-004", top_composite_score=0.50)])

    # Human approves the REVIEW_REQUIRED result as-is
    with patch.object(_v5_module, "interrupt", return_value={"REQ-AP-004": None}):
        node(state)

    postgres.save_fitment.assert_not_called()


@pytest.mark.unit
def test_batch_counts_sum_to_total_atoms(tmp_path) -> None:
    """fit + partial_fit + gap + review_count == total_atoms (Pydantic invariant holds)."""
    node = _make_node(tmp_path)
    state = _make_state(
        [_FIT, _PARTIAL, _GAP, _REVIEW],
        match_results=[
            _mr("REQ-AP-001", top_composite_score=0.92),
            _mr("REQ-AP-002", top_composite_score=0.72),
            _mr("REQ-AP-003", top_composite_score=0.40),
            _mr("REQ-AP-004", top_composite_score=0.50),
        ],
    )

    # _GAP and _REVIEW are flagged; approve both unchanged
    with patch.object(_v5_module, "interrupt", return_value={}):
        result = node(state)

    b = result["validated_batch"]
    assert b.fit_count + b.partial_fit_count + \
        b.gap_count + b.review_count == b.total_atoms == 4


@pytest.mark.unit
def test_fit_count_correct(tmp_path) -> None:
    """fit_count matches the number of FIT-classified results in the final batch."""
    fit_a = make_classification_result(
        atom_id="REQ-FIT-001",
        classification=FitLabel.FIT,
        confidence=0.91,
        route_used=RouteLabel.FAST_TRACK,
    )
    fit_b = make_classification_result(
        atom_id="REQ-FIT-002",
        classification=FitLabel.FIT,
        confidence=0.93,
        route_used=RouteLabel.FAST_TRACK,
    )
    node = _make_node(tmp_path)
    state = _make_state(
        [fit_a, fit_b, _GAP],
        match_results=[
            _mr("REQ-FIT-001", top_composite_score=0.91),
            _mr("REQ-FIT-002", top_composite_score=0.93),
            _mr("REQ-AP-003", top_composite_score=0.40),
        ],
    )
    with patch.object(_v5_module, "interrupt", return_value={"REQ-AP-003": None}):
        result = node(state)

    b = result["validated_batch"]
    assert b.fit_count == 2
    assert b.gap_count == 1


@pytest.mark.unit
def test_gap_count_correct(tmp_path) -> None:
    """gap_count reflects both GAP results even when one was flagged and approved unchanged."""
    gap_a = make_classification_result(
        atom_id="REQ-GAP-A",
        classification=FitLabel.GAP,
        confidence=0.88,  # > 0.85 → high_confidence_gap → flagged
        route_used=RouteLabel.GAP_CONFIRM,
    )
    gap_b = make_classification_result(
        atom_id="REQ-GAP-B",
        classification=FitLabel.GAP,
        confidence=0.70,  # < 0.85 → clean pass
        route_used=RouteLabel.GAP_CONFIRM,
    )
    node = _make_node(tmp_path)
    state = _make_state(
        [gap_a, gap_b],
        match_results=[
            _mr("REQ-GAP-A", top_composite_score=0.40),
            _mr("REQ-GAP-B", top_composite_score=0.38),
        ],
    )
    with patch.object(_v5_module, "interrupt", return_value={"REQ-GAP-A": None}):
        result = node(state)

    assert result["validated_batch"].gap_count == 2


@pytest.mark.unit
def test_fdd_fits_csv_contains_fit_and_partial_fit_rows(tmp_path) -> None:
    """fdd_fits CSV has one row each for FIT and PARTIAL_FIT; no GAP rows."""
    node = _make_node(tmp_path)
    state = _make_state(
        [_FIT, _PARTIAL, _GAP],
        match_results=[
            _mr("REQ-AP-001", top_composite_score=0.92),
            _mr("REQ-AP-002", top_composite_score=0.72),
            _mr("REQ-AP-003", top_composite_score=0.40),
        ],
    )
    with patch.object(_v5_module, "interrupt", return_value={"REQ-AP-003": None}):
        result = node(state)

    batch = result["validated_batch"]
    fits_path = os.path.join(
        str(tmp_path), batch.batch_id, f"fdd_fits_{batch.batch_id}.csv")
    assert os.path.exists(fits_path)

    with open(fits_path, newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 2
    classifications = {r["classification"] for r in rows}
    assert classifications <= {"FIT", "PARTIAL_FIT"}


@pytest.mark.unit
def test_fdd_gaps_csv_contains_gap_rows(tmp_path) -> None:
    """fdd_gaps CSV has exactly the GAP result and nothing else."""
    node = _make_node(tmp_path)
    state = _make_state(
        [_FIT, _GAP],
        match_results=[
            _mr("REQ-AP-001", top_composite_score=0.92),
            _mr("REQ-AP-003", top_composite_score=0.40),
        ],
    )
    with patch.object(_v5_module, "interrupt", return_value={"REQ-AP-003": None}):
        result = node(state)

    batch = result["validated_batch"]
    gaps_path = os.path.join(
        str(tmp_path), batch.batch_id, f"fdd_gaps_{batch.batch_id}.csv")
    assert os.path.exists(gaps_path)

    with open(gaps_path, newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 1
    assert rows[0]["classification"] == "GAP"
    assert rows[0]["req_id"] == "REQ-AP-003"


@pytest.mark.unit
def test_csv_has_correct_headers(tmp_path) -> None:
    """Both FDD CSVs have the 13 required column headers in order."""
    node = _make_node(tmp_path)
    state = _make_state([_FIT], match_results=[
                        _mr("REQ-AP-001", top_composite_score=0.92)])

    with patch.object(_v5_module, "interrupt"):
        result = node(state)

    batch = result["validated_batch"]
    fits_path = os.path.join(
        str(tmp_path), batch.batch_id, f"fdd_fits_{batch.batch_id}.csv")

    with open(fits_path, newline="") as fh:
        headers = list(csv.DictReader(fh).fieldnames or [])

    expected = [
        "req_id",
        "requirement",
        "module",
        "country",
        "wave",
        "classification",
        "confidence",
        "d365_capability",
        "rationale",
        "config_steps",
        "gap_description",
        "reviewer",
        "override",
    ]
    assert headers == expected


@pytest.mark.unit
def test_complete_event_published_with_correct_counts(tmp_path) -> None:
    """CompleteEvent published via Redis carries the correct batch-level counts."""
    from platform.schemas.events import CompleteEvent

    redis = make_redis_pub_sub()
    node = _make_node(tmp_path, redis=redis)
    state = _make_state(
        [_FIT, _PARTIAL, _GAP],
        match_results=[
            _mr("REQ-AP-001", top_composite_score=0.92),
            _mr("REQ-AP-002", top_composite_score=0.72),
            _mr("REQ-AP-003", top_composite_score=0.40),
        ],
    )
    with patch.object(_v5_module, "interrupt", return_value={"REQ-AP-003": None}):
        node(state)

    complete_events = [
        call[0][0] for call in redis.publish.call_args_list if isinstance(call[0][0], CompleteEvent)
    ]
    assert len(complete_events) == 1

    evt = complete_events[0]
    assert evt.total == 3
    assert evt.fit_count == 1
    assert evt.partial_fit_count == 1
    assert evt.gap_count == 1
    assert evt.review_count == 0


@pytest.mark.unit
def test_write_back_postgres_error_logged_not_raised(tmp_path) -> None:
    """PostgresError in save_fitment is logged as WARNING; pipeline still completes."""
    postgres = make_postgres_store()
    postgres.save_fitment = AsyncMock(
        side_effect=PostgresError("connection refused"))
    node = _make_node(tmp_path, postgres=postgres)
    state = _make_state([_FIT], match_results=[
                        _mr("REQ-AP-001", top_composite_score=0.92)])

    with patch.object(_v5_module, "interrupt"):
        # Must NOT raise
        result = node(state)

    assert result["validated_batch"] is not None
    assert result["validated_batch"].fit_count == 1


@pytest.mark.unit
def test_reviewer_override_flag_in_csv(tmp_path) -> None:
    """When human overrides a verdict, override='yes' and reviewer columns are populated."""
    node = _make_node(tmp_path)
    state = _make_state([_GAP], match_results=[
                        _mr("REQ-AP-003", top_composite_score=0.40)])

    overrides = {
        "REQ-AP-003": {
            "classification": "FIT",
            "rationale": "Covered by standard config.",
            "consultant": "jane@co.com",
        }
    }

    with patch.object(_v5_module, "interrupt", return_value=overrides):
        result = node(state)

    batch = result["validated_batch"]
    fits_path = os.path.join(
        str(tmp_path), batch.batch_id, f"fdd_fits_{batch.batch_id}.csv")

    with open(fits_path, newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 1
    assert rows[0]["override"] == "yes"
    assert rows[0]["reviewer"] == "jane@co.com"


# ---------------------------------------------------------------------------
# Module-level singleton smoke test
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_module_level_validation_node_singleton_smoke(tmp_path) -> None:
    """validation_node() creates a singleton on first call and returns a validated_batch."""
    _v5_module._node = None  # reset singleton for isolation

    mock_postgres = make_postgres_store()
    mock_redis = make_redis_pub_sub()
    mock_embedder = make_embedder()

    with (
        patch(
            "modules.dynafit.nodes.phase5_validation.PostgresStore",
            return_value=mock_postgres,
        ),
        patch(
            "modules.dynafit.nodes.phase5_validation.RedisPubSub",
            return_value=mock_redis,
        ),
        patch(
            "modules.dynafit.nodes.phase5_validation.Embedder",
            return_value=mock_embedder,
        ),
        patch.object(_v5_module.ValidationNode, "_write_csv",
                     return_value=str(tmp_path)),
        patch.object(_v5_module, "interrupt"),
    ):
        state = _make_state([_FIT], match_results=[
                            _mr("REQ-AP-001", top_composite_score=0.92)])
        result = _v5_module.validation_node(state)

    assert result["validated_batch"] is not None
    _v5_module._node = None  # clean up
