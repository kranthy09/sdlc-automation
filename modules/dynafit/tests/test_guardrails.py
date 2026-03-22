"""G10-lite sanity gate unit tests.

Run with: uv run python -m pytest modules/dynafit/tests/ -v
"""

import pytest

from modules.dynafit.guardrails import run_sanity_check
from platform.schemas.fitment import FitLabel, RouteLabel
from platform.testing.factories import (
    make_classification_result,
    make_match_result,
    make_product_config,
)

# Default config: fit_confidence_threshold=0.85, review_confidence_threshold=0.60
_CONFIG = make_product_config()


@pytest.mark.unit
def test_high_confidence_gap_flagged():
    # confidence 0.92 > fit_confidence_threshold (0.85) + GAP → flag
    result = make_classification_result(
        classification=FitLabel.GAP, confidence=0.92
    )
    flags = run_sanity_check(result, make_match_result(), _CONFIG)
    assert "high_confidence_gap" in flags


@pytest.mark.unit
def test_low_score_fit_flagged():
    # composite 0.45 < review_confidence_threshold (0.60) + FIT → flag
    result = make_classification_result(classification=FitLabel.FIT)
    match = make_match_result(top_composite_score=0.45)
    flags = run_sanity_check(result, match, _CONFIG)
    assert "low_score_fit" in flags


@pytest.mark.unit
def test_llm_retry_exhausted_flagged():
    # classification=REVIEW_REQUIRED → llm_schema_retry_exhausted flag
    result = make_classification_result(
        classification=FitLabel.REVIEW_REQUIRED,
        route_used=RouteLabel.DEEP_REASON,
    )
    flags = run_sanity_check(result, make_match_result(), _CONFIG)
    assert "llm_schema_retry_exhausted" in flags


@pytest.mark.unit
def test_clean_fit_no_flags():
    # FIT, confidence 0.80 < 0.85, composite 0.88 > 0.60 → no flags
    result = make_classification_result(
        classification=FitLabel.FIT,
        confidence=0.80,
        route_used=RouteLabel.FAST_TRACK,
    )
    match = make_match_result(top_composite_score=0.88)
    flags = run_sanity_check(result, match, _CONFIG)
    assert flags == []
