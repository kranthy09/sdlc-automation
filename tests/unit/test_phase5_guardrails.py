"""
Unit tests for G10-lite: modules/dynafit/guardrails.py (Session G, Sub-phase 5A).

All tests are @pytest.mark.unit — no Docker, no LangGraph, no async.
Each test exercises run_sanity_check() in isolation.

Coverage:
  Rule 1 — high_confidence_gap:
    - GAP + confidence above fit_confidence_threshold → flagged
    - GAP + confidence below threshold → not flagged
    - GAP + confidence exactly equal to threshold → not flagged (boundary: strict >)

  Rule 2 — low_score_fit:
    - FIT + composite_score below review_confidence_threshold → flagged
    - FIT + composite_score above threshold → not flagged
    - FIT + composite_score exactly equal to threshold → not flagged (boundary: strict <)

  Rule 3 — llm_schema_retry_exhausted:
    - route_used == REVIEW_REQUIRED → flagged
    - route_used != REVIEW_REQUIRED → not flagged

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
    make_match_result,
    make_product_config,
    make_classification_result,
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
def test_review_required_route_flagged(config) -> None:
    """route_used == REVIEW_REQUIRED → llm_schema_retry_exhausted flag."""
    result = make_classification_result(
        classification=FitLabel.REVIEW_REQUIRED,
        confidence=0.0,
        route_used=RouteLabel.REVIEW_REQUIRED,
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
def test_multiple_flags_rules_1_and_3(config) -> None:
    """GAP with high confidence (rule 1) + REVIEW_REQUIRED route (rule 3) → both flags."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.91,
        route_used=RouteLabel.REVIEW_REQUIRED,
    )
    mr = make_match_result(top_composite_score=0.40)

    flags = run_sanity_check(result, mr, config)

    assert "high_confidence_gap" in flags
    assert "llm_schema_retry_exhausted" in flags


@pytest.mark.unit
def test_multiple_flags_rules_2_and_3(config) -> None:
    """FIT with low composite (rule 2) + REVIEW_REQUIRED route (rule 3) → both flags."""
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.92,
        route_used=RouteLabel.REVIEW_REQUIRED,
    )
    mr = make_match_result(top_composite_score=0.45)

    flags = run_sanity_check(result, mr, config)

    assert "low_score_fit" in flags
    assert "llm_schema_retry_exhausted" in flags


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
def test_clean_gap_low_confidence_returns_empty_flags(config) -> None:
    """Sane GAP result (low confidence, consistent with weak composite) → no flags."""
    result = make_classification_result(
        classification=FitLabel.GAP,
        confidence=0.80,  # < fit_threshold: rule 1 does NOT trigger
        route_used=RouteLabel.GAP_CONFIRM,
    )
    mr = make_match_result(top_composite_score=0.38)

    flags = run_sanity_check(result, mr, config)

    assert flags == []


@pytest.mark.unit
def test_clean_partial_fit_returns_empty_flags(config) -> None:
    """Sane PARTIAL_FIT result → no flags."""
    result = make_classification_result(
        classification=FitLabel.PARTIAL_FIT,
        confidence=0.78,
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
