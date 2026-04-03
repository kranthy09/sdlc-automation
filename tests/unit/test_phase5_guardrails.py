"""
Unit tests for Phase 5 sanity gate: modules/dynafit/guardrails.py (Session G, Sub-phase 5A).

All tests are @pytest.mark.unit — no Docker, no LangGraph, no async.
Each test exercises run_sanity_check() in isolation.

Coverage:
  Rule 1 — high_confidence_gap (G10-lite):
    - GAP + confidence above fit_confidence_threshold → flagged
    - GAP + confidence below threshold → not flagged
    - GAP + confidence exactly equal to threshold → not flagged (boundary: strict >)

  Rule 2 — low_score_fit (G10-lite):
    - FIT + composite_score below review_confidence_threshold → flagged
    - FIT + composite_score above threshold → not flagged
    - FIT + composite_score exactly equal to threshold → not flagged (boundary: strict <)

  Rule 3 — llm_schema_retry_exhausted (G10-lite):
    - classification == REVIEW_REQUIRED → flagged
    - classification != REVIEW_REQUIRED → not flagged

  Rule 4 — low_confidence (Phase 5 validation):
    - Non-GAP, non-REVIEW_REQUIRED result with confidence < review threshold → flagged
    - FIT/PARTIAL_FIT with high confidence → not flagged

  Rule 5 — gap_review (Phase 5 validation):
    - classification == GAP → always flagged (mandatory analyst review)
    - Non-GAP results → not flagged by this rule

  Rule 6 — phase3_anomaly (Phase 5 validation):
    - match.anomaly_flags is non-empty → flagged
    - match.anomaly_flags is empty → not flagged

  Rule 7 — response_pii_leak (G11 guardrail):
    - "G11:" in result.caveats → flagged
    - No "G11:" in caveats → not flagged

  Rule 8 — partial_fit_no_config (Phase 5 validation):
    - PARTIAL_FIT without config_steps/configuration_steps → flagged
    - PARTIAL_FIT with config_steps → not flagged

  Multi-flag:
    - Multiple rules triggered in one result → all flags returned

  No-flag:
    - Sane result → empty list
"""

from __future__ import annotations

import pytest

from modules.dynafit.guardrails import run_sanity_check
from platform.schemas.fitment import FitLabel, RouteLabel
from platform.testing.factories import (
    make_classification_result,
    make_match_result,
    make_product_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config():
    """Standard D365 F&O config: fit_threshold=0.85, review_threshold=0.60."""
    return make_product_config(
        fit_confidence_threshold=0.85,
        review_confidence_threshold=0.60,
    )


# ---------------------------------------------------------------------------
# Rule 1: high_confidence_gap
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_high_confidence_gap_flagged(config) -> None:
    """GAP verdict with confidence above fit_confidence_threshold → flag."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.91,  # > 0.85
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.88)

    flags = run_sanity_check(result, mr, config)

    assert "high_confidence_gap" in flags


@pytest.mark.unit
def test_high_confidence_gap_below_threshold_not_flagged(config) -> None:
    """GAP with confidence below threshold → no flag."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.70,  # < 0.85
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.40)

    flags = run_sanity_check(result, mr, config)

    assert "high_confidence_gap" not in flags


@pytest.mark.unit
def test_high_confidence_gap_exactly_at_threshold_not_flagged(config) -> None:
    """Boundary: confidence == fit_confidence_threshold → NOT flagged (rule is strict >)."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.85,  # exactly equal — should NOT trigger
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.40)

    flags = run_sanity_check(result, mr, config)

    assert "high_confidence_gap" not in flags


@pytest.mark.unit
def test_fit_with_high_confidence_not_flagged_by_rule1(config) -> None:
    """Rule 1 only applies to GAP — FIT with high confidence is clean."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.95,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.92)

    flags = run_sanity_check(result, mr, config)

    assert "high_confidence_gap" not in flags


# ---------------------------------------------------------------------------
# Rule 2: low_score_fit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_low_score_fit_flagged(config) -> None:
    """FIT verdict with composite score below review_confidence_threshold → flag."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.90,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.45)  # < 0.60

    flags = run_sanity_check(result, mr, config)

    assert "low_score_fit" in flags


@pytest.mark.unit
def test_low_score_fit_above_threshold_not_flagged(config) -> None:
    """FIT with composite above threshold → no flag."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.90,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.72)  # > 0.60

    flags = run_sanity_check(result, mr, config)

    assert "low_score_fit" not in flags


@pytest.mark.unit
def test_low_score_fit_exactly_at_threshold_not_flagged(config) -> None:
    """Boundary: composite == review_confidence_threshold → NOT flagged (strict <)."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.90,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.60)  # exactly equal

    flags = run_sanity_check(result, mr, config)

    assert "low_score_fit" not in flags


@pytest.mark.unit
def test_partial_fit_low_composite_not_flagged_by_rule2(config) -> None:
    """Rule 2 only applies to FIT — PARTIAL_FIT with low composite is clean."""
    result = make_classification_result(
        classification=FitLabel.PARTIAL_FIT,
        confidence=0.78,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.45)

    flags = run_sanity_check(result, mr, config)

    assert "low_score_fit" not in flags


# ---------------------------------------------------------------------------
# Rule 3: llm_schema_retry_exhausted
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_review_required_classification_flagged(config) -> None:
    """classification == REVIEW_REQUIRED → llm_schema_retry_exhausted flag."""
    result = make_classification_result(
        classification=FitLabel.REVIEW_REQUIRED,
        confidence=0.0,
        route_used=RouteLabel.FAST_TRACK,  # Use any valid route
    )
    mr = make_match_result(top_composite_score=0.70)

    flags = run_sanity_check(result, mr, config)

    assert "llm_schema_retry_exhausted" in flags


@pytest.mark.unit
def test_fast_track_route_not_flagged_by_rule3(config) -> None:
    """FAST_TRACK route → rule 3 does not trigger."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.92,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.92)

    flags = run_sanity_check(result, mr, config)

    assert "llm_schema_retry_exhausted" not in flags


# ---------------------------------------------------------------------------
# Multi-flag: two or more rules triggered simultaneously
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_multiple_flags_rules_1_5(config) -> None:
    """GAP with high confidence (rule 1) + gap_review (rule 5) → both flags."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.91,  # > 0.85 → rule 1
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.40)

    flags = run_sanity_check(result, mr, config)

    assert "high_confidence_gap" in flags
    assert "gap_review" in flags


@pytest.mark.unit
def test_multiple_flags_rules_2_and_4(config) -> None:
    """FIT with low composite (rule 2) + low confidence (rule 4) → both flags."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.55,  # < 0.60 → rule 4
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.45)  # < 0.60 → rule 2

    flags = run_sanity_check(result, mr, config)

    assert "low_score_fit" in flags
    assert "low_confidence" in flags


# ---------------------------------------------------------------------------
# Clean result — no flags
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clean_fit_high_composite_returns_empty_flags(config) -> None:
    """Sane FIT result → empty flag list (no HITL needed)."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.92,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.91)

    flags = run_sanity_check(result, mr, config)

    assert flags == []


@pytest.mark.unit
def test_gap_always_flagged_for_mandatory_review(config) -> None:
    """All GAP results trigger gap_review rule (mandatory analyst sign-off)."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.80,
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.38)

    flags = run_sanity_check(result, mr, config)

    # GAPs always trigger gap_review (rule 5) — mandatory analyst review
    assert "gap_review" in flags
    # But not other rules in this case
    assert "high_confidence_gap" not in flags


@pytest.mark.unit
def test_clean_partial_fit_with_config_steps_returns_empty_flags(config) -> None:
    """PARTIAL_FIT with config_steps provided → no flags."""
    result = make_classification_result(
        classification=FitLabel.PARTIAL_FIT,
        confidence=0.78,
        config_steps="Configure the AP module in System Administration > Setup > Accounts Payable.",
        route_used=RouteLabel.DEEP_REASON,
    )
    mr = make_match_result(top_composite_score=0.72)

    flags = run_sanity_check(result, mr, config)

    assert flags == []


# ---------------------------------------------------------------------------
# Custom thresholds respected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_custom_thresholds_applied() -> None:
    """run_sanity_check reads thresholds from config — not hardcoded constants."""
    tight_config = make_product_config(
        fit_confidence_threshold=0.70,  # lower than standard
        review_confidence_threshold=0.50,
    )
    # confidence=0.75 > 0.70 → triggers rule 1 with tight threshold
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.75,
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.40)

    flags = run_sanity_check(result, mr, tight_config)

    assert "high_confidence_gap" in flags


@pytest.mark.unit
def test_standard_threshold_does_not_flag_below_tight_threshold(config) -> None:
    """confidence=0.75 does NOT trigger rule 1 with standard threshold (0.85)."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.75,  # < 0.85 → below standard threshold
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.40)

    flags = run_sanity_check(result, mr, config)

    assert "high_confidence_gap" not in flags


# ---------------------------------------------------------------------------
# Rule 4: low_confidence
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_low_confidence_flagged_for_fit(config) -> None:
    """FIT result with confidence below review_confidence_threshold → flag."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.55,  # < 0.60
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.80)

    flags = run_sanity_check(result, mr, config)

    assert "low_confidence" in flags


@pytest.mark.unit
def test_low_confidence_flagged_for_partial_fit(config) -> None:
    """PARTIAL_FIT result with confidence below review_confidence_threshold → flag."""
    result = make_classification_result(
        classification=FitLabel.PARTIAL_FIT,
        confidence=0.50,  # < 0.60
        config_steps="Some configuration",
        route_used=RouteLabel.DEEP_REASON,
    )
    mr = make_match_result(top_composite_score=0.72)

    flags = run_sanity_check(result, mr, config)

    assert "low_confidence" in flags


@pytest.mark.unit
def test_low_confidence_not_flagged_above_threshold(config) -> None:
    """FIT with confidence above threshold → rule 4 does not trigger."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.65,  # > 0.60
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.72)

    flags = run_sanity_check(result, mr, config)

    assert "low_confidence" not in flags


@pytest.mark.unit
def test_low_confidence_not_flagged_for_gap(config) -> None:
    """GAP result → rule 4 does not apply (rule 5 applies instead)."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.50,  # Below threshold, but rule 4 doesn't apply to GAP
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.30)

    flags = run_sanity_check(result, mr, config)

    # rule 5 (gap_review) triggers, but not rule 4
    assert "gap_review" in flags
    assert "low_confidence" not in flags


# ---------------------------------------------------------------------------
# Rule 5: gap_review
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_gap_review_always_flagged(config) -> None:
    """All GAP classifications → gap_review flag."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.95,  # Even high confidence GAPs require review
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.88)

    flags = run_sanity_check(result, mr, config)

    # Both rule 1 (high_confidence_gap) and rule 5 (gap_review) trigger
    assert "gap_review" in flags
    assert "high_confidence_gap" in flags


@pytest.mark.unit
def test_gap_review_not_flagged_for_fit(config) -> None:
    """FIT classification → rule 5 does not trigger."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.85,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.88)

    flags = run_sanity_check(result, mr, config)

    assert "gap_review" not in flags


# ---------------------------------------------------------------------------
# Rule 6: phase3_anomaly
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_phase3_anomaly_flagged(config) -> None:
    """MatchResult with anomaly_flags → phase3_anomaly flag."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.88,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(
        top_composite_score=0.88,
        anomaly_flags=["data_quality_issue", "retrieval_confidence_low"],
    )

    flags = run_sanity_check(result, mr, config)

    assert "phase3_anomaly" in flags


@pytest.mark.unit
def test_phase3_anomaly_not_flagged_empty_list(config) -> None:
    """MatchResult with empty anomaly_flags → no phase3_anomaly flag."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.88,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.88, anomaly_flags=[])

    flags = run_sanity_check(result, mr, config)

    assert "phase3_anomaly" not in flags


@pytest.mark.unit
def test_phase3_anomaly_not_flagged_none_match(config) -> None:
    """When match is None → rule 6 does not trigger."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.88,
        route_used=RouteLabel.FAST_TRACK,
    )

    flags = run_sanity_check(result, None, config)

    assert "phase3_anomaly" not in flags


# ---------------------------------------------------------------------------
# Rule 7: response_pii_leak (G11 guardrail)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_response_pii_leak_flagged(config) -> None:
    """"G11:" in result.caveats → response_pii_leak flag."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.88,
        caveats="G11: PII detected in LLM response — personal identifiable information found",
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.88)

    flags = run_sanity_check(result, mr, config)

    assert "response_pii_leak" in flags


@pytest.mark.unit
def test_response_pii_leak_not_flagged_no_g11(config) -> None:
    """Caveats without "G11:" prefix → rule 7 does not trigger."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.88,
        caveats="Some non-PII caveat about the response",
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.88)

    flags = run_sanity_check(result, mr, config)

    assert "response_pii_leak" not in flags


@pytest.mark.unit
def test_response_pii_leak_not_flagged_empty_caveats(config) -> None:
    """Empty or None caveats → rule 7 does not trigger."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.88,
        caveats=None,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.88)

    flags = run_sanity_check(result, mr, config)

    assert "response_pii_leak" not in flags


# ---------------------------------------------------------------------------
# Rule 8: partial_fit_no_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_partial_fit_no_config_flagged(config) -> None:
    """PARTIAL_FIT without config_steps/configuration_steps → flag."""
    result = make_classification_result(
        classification=FitLabel.PARTIAL_FIT,
        confidence=0.78,
        config_steps=None,
        configuration_steps=None,
        route_used=RouteLabel.DEEP_REASON,
    )
    mr = make_match_result(top_composite_score=0.72)

    flags = run_sanity_check(result, mr, config)

    assert "partial_fit_no_config" in flags


@pytest.mark.unit
def test_partial_fit_with_config_steps_not_flagged(config) -> None:
    """PARTIAL_FIT with config_steps → rule 8 does not trigger."""
    result = make_classification_result(
        classification=FitLabel.PARTIAL_FIT,
        confidence=0.78,
        config_steps="Configure the AP module in System Administration.",
        route_used=RouteLabel.DEEP_REASON,
    )
    mr = make_match_result(top_composite_score=0.72)

    flags = run_sanity_check(result, mr, config)

    assert "partial_fit_no_config" not in flags


@pytest.mark.unit
def test_partial_fit_with_configuration_steps_not_flagged(config) -> None:
    """PARTIAL_FIT with configuration_steps (list) → rule 8 does not trigger."""
    result = make_classification_result(
        classification=FitLabel.PARTIAL_FIT,
        confidence=0.78,
        configuration_steps=["Configure AP module in System Administration"],
        config_steps=None,  # Only configuration_steps is set
        route_used=RouteLabel.DEEP_REASON,
    )
    mr = make_match_result(top_composite_score=0.72)

    flags = run_sanity_check(result, mr, config)

    assert "partial_fit_no_config" not in flags


@pytest.mark.unit
def test_partial_fit_no_config_not_flagged_for_fit(config) -> None:
    """FIT classification → rule 8 does not trigger (no config needed)."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.92,
        config_steps=None,
        route_used=RouteLabel.FAST_TRACK,
    )
    mr = make_match_result(top_composite_score=0.92)

    flags = run_sanity_check(result, mr, config)

    assert "partial_fit_no_config" not in flags


# ---------------------------------------------------------------------------
# None match: ensure rules requiring match handle None gracefully
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_none_match_skips_rules_1_2_6(config) -> None:
    """When match is None, rules 1, 2, 6 are safely skipped."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.50,  # Would trigger rule 4 (low_confidence)
        route_used=RouteLabel.FAST_TRACK,
    )

    flags = run_sanity_check(result, None, config)

    # Rules 1, 2, 6 skipped (require match)
    assert "high_confidence_gap" not in flags
    assert "low_score_fit" not in flags
    assert "phase3_anomaly" not in flags
    # But rule 4 still triggers
    assert "low_confidence" in flags
