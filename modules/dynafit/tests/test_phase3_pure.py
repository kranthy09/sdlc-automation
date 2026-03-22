"""Pure-function unit tests for Phase 3 matching helpers.

No infrastructure — all four functions are module-level and deterministic.
Run with: uv run python -m pytest modules/dynafit/tests/ -v
"""

import pytest

from modules.dynafit.nodes.matching import (
    _HISTORY_BOOST,
    _assign_route,
    _compute_composite,
    _detect_anomaly,
    _entity_overlap_score,
)
from platform.schemas.fitment import RouteLabel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ONES = {
    "embedding_cosine": 1.0,
    "entity_overlap": 1.0,
    "token_ratio": 1.0,
    "historical_alignment": 1.0,
    "rerank_score": 1.0,
}


def _signals(**overrides: float) -> dict[str, float]:
    return {**_ONES, **overrides}


# ---------------------------------------------------------------------------
# _compute_composite
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_composite_all_ones():
    assert _compute_composite(_ONES) == pytest.approx(1.0)


@pytest.mark.unit
def test_composite_weighted():
    # 0.8×0.25 + 0.5×0.20 + 0.6×0.15 + 0.4×0.25 + 0.3×0.15 = 0.535
    signals = {
        "embedding_cosine": 0.8,
        "entity_overlap": 0.5,
        "token_ratio": 0.6,
        "historical_alignment": 0.4,
        "rerank_score": 0.3,
    }
    expected = 0.8 * 0.25 + 0.5 * 0.20 + 0.6 * 0.15 + 0.4 * 0.25 + 0.3 * 0.15
    assert _compute_composite(signals) == pytest.approx(expected, abs=1e-9)


@pytest.mark.unit
def test_composite_history_boost_caps_at_one():
    # composite ≈ 0.95; adding _HISTORY_BOOST (0.10) must stay ≤ 1.0
    signals = {k: 0.95 for k in _ONES}
    composite = _compute_composite(signals)  # 0.95
    boosted = min(1.0, composite + _HISTORY_BOOST)
    assert boosted <= 1.0


# ---------------------------------------------------------------------------
# _assign_route
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_assign_route_fast_track():
    # composite > 0.85 AND history → FAST_TRACK
    assert _assign_route(0.90, has_history=True) == RouteLabel.FAST_TRACK


@pytest.mark.unit
def test_assign_route_deep_reason():
    # 0.60 ≤ composite ≤ 0.85 → DEEP_REASON
    assert _assign_route(0.72, has_history=False) == RouteLabel.DEEP_REASON


@pytest.mark.unit
def test_assign_route_gap_confirm():
    # composite < 0.60 → GAP_CONFIRM
    assert _assign_route(0.45, has_history=False) == RouteLabel.GAP_CONFIRM


# ---------------------------------------------------------------------------
# _detect_anomaly
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_anomaly_fires_high_cosine_low_entity():
    # cosine > 0.85 AND entity_overlap < 0.20 → flag string returned
    assert _detect_anomaly(embedding_cosine=0.87, entity_overlap=0.15) is not None


@pytest.mark.unit
def test_anomaly_no_fire_high_entity():
    # entity_overlap ≥ 0.20 suppresses the flag even at high cosine
    assert _detect_anomaly(embedding_cosine=0.87, entity_overlap=0.25) is None


@pytest.mark.unit
def test_anomaly_no_fire_low_cosine():
    # cosine ≤ 0.85 never triggers the anomaly
    assert _detect_anomaly(embedding_cosine=0.80, entity_overlap=0.10) is None


# ---------------------------------------------------------------------------
# _entity_overlap_score
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_entity_overlap_exact_match():
    score = _entity_overlap_score(["matching"], "three-way matching for invoices")
    assert score > 0.0


@pytest.mark.unit
def test_entity_overlap_no_hints():
    assert _entity_overlap_score([], "any capability description") == 0.0
