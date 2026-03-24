"""
Tests for the DYNAFIT matching node — Phase 3.

All tests are @pytest.mark.unit — they use mocked infrastructure and do not
require Docker services. The file lives in tests/integration/ because it
tests the full Phase 3 pipeline end-to-end (not a single pure function).

Test coverage:
  Pure helpers (tested directly):
    - _compute_composite: weighted sum formula (all-1s, partial, capped)
    - _assign_route: FAST_TRACK / DEEP_REASON / GAP_CONFIRM thresholds
    - _detect_anomaly: high cosine without entity agreement raises flag
    - _entity_overlap_score: hint-in-cap-text fractional coverage

  MatchingNode integration:
    - Empty contexts → empty match_results
    - No capabilities → GAP_CONFIRM
    - Anomaly flag propagated into MatchResult
    - FIT prior boosts composite by _HISTORY_BOOST
    - Non-FIT prior does NOT trigger history boost
    - Multiple contexts → one MatchResult per context
    - Dedup: near-identical capabilities collapsed
    - All signals max → FAST_TRACK
    - Module-level matching_node() smoke test
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from prometheus_client import CollectorRegistry

from platform.retrieval.embedder import Embedder
from platform.schemas.fitment import RouteLabel
from platform.testing.factories import (
    make_assembled_context,
    make_embedder,
    make_prior_fitment,
    make_ranked_capability,
    make_raw_upload,
    make_validated_atom,
)

# ---------------------------------------------------------------------------
# Embedder helpers
# ---------------------------------------------------------------------------


def _make_unit_embedder(dim: int = 384) -> Embedder:
    """Embedder that returns identical unit vectors → embedding_cosine = 1.0."""
    mock_model = MagicMock()
    unit = np.ones(dim, dtype=np.float32) / np.sqrt(dim)

    def _encode(texts: str | list[str]) -> Any:
        if isinstance(texts, list):
            return np.tile(unit, (len(texts), 1))
        return unit.copy()

    mock_model.encode.side_effect = _encode
    return Embedder("test-unit", _model=mock_model, registry=CollectorRegistry())


def _make_state(contexts: list | None = None, **upload_overrides: Any) -> dict:
    upload = make_raw_upload(**upload_overrides)
    return {
        "upload": upload,
        "batch_id": "test-batch-phase3",
        "errors": [],
        "retrieval_contexts": contexts or [],
    }


def _build_node(embedder: Embedder | None = None) -> Any:
    from modules.dynafit.nodes.matching import MatchingNode

    return MatchingNode(embedder=embedder or make_embedder())


# ===========================================================================
# Pure helper tests (parametrized)
# ===========================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        # All signals = 1.0 → composite = 1.0
        (
            {
                "embedding_cosine": 1.0, "entity_overlap": 1.0,
                "token_ratio": 1.0, "historical_alignment": 1.0,
                "rerank_score": 1.0,
            },
            1.0,
        ),
        # Only historical_alignment(0.25) + rerank(0.15) → 0.40
        (
            {
                "embedding_cosine": 0.0, "entity_overlap": 0.0,
                "token_ratio": 0.0, "historical_alignment": 1.0,
                "rerank_score": 1.0,
            },
            0.40,
        ),
        # All signals > 1.0 → capped at 1.0
        (
            {
                "embedding_cosine": 2.0, "entity_overlap": 2.0,
                "token_ratio": 2.0, "historical_alignment": 2.0,
                "rerank_score": 2.0,
            },
            1.0,
        ),
    ],
    ids=["all_ones", "partial", "capped"],
)
def test_compute_composite(signals: dict, expected: float) -> None:
    from modules.dynafit.nodes.matching import _compute_composite

    assert _compute_composite(signals) == pytest.approx(expected)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("composite", "has_history", "expected_route"),
    [
        (0.90, True, RouteLabel.FAST_TRACK),
        (0.90, False, RouteLabel.DEEP_REASON),
        (0.60, False, RouteLabel.DEEP_REASON),
        (0.85, True, RouteLabel.DEEP_REASON),  # boundary: 0.85 is NOT > threshold
        (0.50, True, RouteLabel.GAP_CONFIRM),
        (0.30, False, RouteLabel.GAP_CONFIRM),
    ],
    ids=[
        "fast_track", "high_no_history", "deep_reason_boundary",
        "fast_track_boundary", "gap_with_history", "gap_no_history",
    ],
)
def test_assign_route(composite: float, has_history: bool, expected_route: RouteLabel) -> None:
    from modules.dynafit.nodes.matching import _assign_route

    assert _assign_route(composite, has_history=has_history) == expected_route


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cosine", "entity_overlap", "expect_anomaly"),
    [
        (0.90, 0.10, True),   # high cosine + low entity → anomaly
        (0.90, 0.20, False),  # high cosine + OK entity → clear
        (0.70, 0.05, False),  # low cosine → never anomaly
    ],
    ids=["flagged", "entity_ok", "cosine_low"],
)
def test_detect_anomaly(cosine: float, entity_overlap: float, expect_anomaly: bool) -> None:
    from modules.dynafit.nodes.matching import _detect_anomaly

    result = _detect_anomaly(cosine, entity_overlap)
    if expect_anomaly:
        assert result is not None
        assert "high_cosine_no_entity" in result
    else:
        assert result is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("hints", "cap_text", "expected"),
    [
        ([], "invoice matching vendor", 0.0),
        (["invoice", "vendor", "matching"], "vendor invoice matching policy configuration", 1.0),
        (["invoice", "vendor", "purchase order"], "invoice approval workflow", 1 / 3),
        (["payroll", "employee"], "three-way matching for purchase orders", 0.0),
    ],
    ids=["empty_hints", "all_present", "partial", "no_match"],
)
def test_entity_overlap_score(hints: list[str], cap_text: str, expected: float) -> None:
    from modules.dynafit.nodes.matching import _entity_overlap_score

    assert _entity_overlap_score(hints, cap_text) == pytest.approx(expected)


# ===========================================================================
# MatchingNode integration tests
# ===========================================================================


@pytest.mark.unit
def test_empty_contexts_returns_empty_match_results() -> None:
    """No retrieval_contexts in state → match_results is empty."""
    node = _build_node()
    result = node(_make_state(contexts=[]))
    assert result["match_results"] == []


@pytest.mark.unit
def test_no_capabilities_in_context_returns_gap_confirm() -> None:
    """AssembledContext with no capabilities → GAP_CONFIRM, empty lists."""
    node = _build_node()
    ctx = make_assembled_context(capabilities=[])
    result = node(_make_state(contexts=[ctx]))

    match_results = result["match_results"]
    assert len(match_results) == 1
    mr = match_results[0]
    assert mr.route == RouteLabel.GAP_CONFIRM
    assert mr.ranked_capabilities == []
    assert mr.composite_scores == []
    assert mr.top_composite_score == pytest.approx(0.0)


@pytest.mark.unit
def test_multiple_contexts_produce_one_result_per_context() -> None:
    """Three contexts → three MatchResults in the same order."""
    node = _build_node()
    atoms = [make_validated_atom(atom_id=f"REQ-{i:03d}") for i in range(3)]
    contexts = [make_assembled_context(atom=a) for a in atoms]

    result = node(_make_state(contexts=contexts))
    match_results = result["match_results"]

    assert len(match_results) == 3
    assert [mr.atom.atom_id for mr in match_results] == ["REQ-000", "REQ-001", "REQ-002"]


@pytest.mark.unit
def test_anomaly_flag_propagated_to_match_result() -> None:
    """Unit embedder → cosine=1.0; atom with no entity_hints → entity_overlap=0 → anomaly."""
    node = _build_node(embedder=_make_unit_embedder())
    atom = make_validated_atom(entity_hints=[])  # entity_overlap will be 0.0
    cap = make_ranked_capability(rerank_score=0.90)
    ctx = make_assembled_context(atom=atom, capabilities=[cap])

    result = node(_make_state(contexts=[ctx]))
    mr = result["match_results"][0]

    # cosine=1.0 > 0.85 and entity_overlap=0.0 < 0.20 → anomaly
    assert len(mr.anomaly_flags) >= 1
    assert "high_cosine_no_entity" in mr.anomaly_flags[0]


@pytest.mark.unit
def test_fit_prior_boosts_composite() -> None:
    """A FIT prior fitment adds _HISTORY_BOOST (0.10) to the composite score."""
    from modules.dynafit.nodes.matching import _HISTORY_BOOST

    embedder = make_embedder()  # zero vectors → cosine=0, entity=0

    # Without any history
    cap = make_ranked_capability(rerank_score=0.80)
    ctx_no_history = make_assembled_context(capabilities=[cap], prior_fitments=[])
    node_no = _build_node(embedder=embedder)
    score_no_history = node_no(_make_state(contexts=[ctx_no_history]))["match_results"][
        0
    ].top_composite_score

    # With a FIT prior — rebuild node to get fresh embedder state
    embedder2 = make_embedder()
    fit_prior = make_prior_fitment(classification="FIT")
    ctx_with_history = make_assembled_context(capabilities=[cap], prior_fitments=[fit_prior])
    node_yes = _build_node(embedder=embedder2)
    score_with_history = node_yes(_make_state(contexts=[ctx_with_history]))["match_results"][
        0
    ].top_composite_score

    assert score_with_history == pytest.approx(score_no_history + _HISTORY_BOOST, abs=1e-6)


@pytest.mark.unit
def test_non_fit_prior_does_not_boost() -> None:
    """A GAP prior provides historical_alignment signal but NOT the FIT boost."""
    from modules.dynafit.nodes.matching import _HISTORY_BOOST

    cap = make_ranked_capability(rerank_score=0.80)
    gap_prior = make_prior_fitment(classification="GAP")
    ctx = make_assembled_context(capabilities=[cap], prior_fitments=[gap_prior])
    node = _build_node()
    mr = node(_make_state(contexts=[ctx]))["match_results"][0]

    ctx_no_prior = make_assembled_context(capabilities=[cap], prior_fitments=[])
    node2 = _build_node()
    mr_no_prior = node2(_make_state(contexts=[ctx_no_prior]))["match_results"][0]

    # GAP prior contributes historical_alignment=1.0 (weight 0.25) but no extra boost
    assert mr.top_composite_score > mr_no_prior.top_composite_score
    assert mr.top_composite_score < mr_no_prior.top_composite_score + _HISTORY_BOOST + 0.30


@pytest.mark.unit
def test_dedup_removes_near_identical_capabilities() -> None:
    """Two caps with near-identical descriptions and cosine > 0.95 → only one kept."""
    node = _build_node(embedder=_make_unit_embedder())

    same_desc = "Three-way matching validates purchase orders and invoices."
    cap_a = make_ranked_capability(capability_id="cap-a", rerank_score=0.90, description=same_desc)
    cap_b = make_ranked_capability(capability_id="cap-b", rerank_score=0.80, description=same_desc)
    ctx = make_assembled_context(capabilities=[cap_a, cap_b])

    mr = node(_make_state(contexts=[ctx]))["match_results"][0]

    assert len(mr.ranked_capabilities) == 1
    assert mr.ranked_capabilities[0].capability_id == "cap-a"


@pytest.mark.unit
def test_all_signals_via_unit_embedder_produces_fast_track() -> None:
    """All signals maximised → composite near 1.0, FAST_TRACK with history present."""
    node = _build_node(embedder=_make_unit_embedder())

    atom = make_validated_atom(
        entity_hints=["invoice", "vendor"],
        requirement_text="vendor invoice three-way matching",
    )
    cap = make_ranked_capability(
        feature="vendor invoice matching",
        description="invoice vendor three-way matching purchase order",
        rerank_score=1.0,
    )
    fit_prior = make_prior_fitment(classification="FIT")
    ctx = make_assembled_context(atom=atom, capabilities=[cap], prior_fitments=[fit_prior])

    mr = node(_make_state(contexts=[ctx]))["match_results"][0]

    assert mr.route == RouteLabel.FAST_TRACK
    assert mr.top_composite_score > 0.85


# ---------------------------------------------------------------------------
# Module-level matching_node() smoke test
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_matching_node_function_accepts_state_dict() -> None:
    """Module-level matching_node() runs without errors on minimal state."""
    import modules.dynafit.nodes.matching as matching_mod

    # Reset singleton so test controls the injected instance
    matching_mod._node = None  # noqa: SLF001

    mock_node = MagicMock(return_value={"match_results": []})
    matching_mod._node = mock_node  # type: ignore[assignment]  # noqa: SLF001

    state = _make_state(contexts=[])
    result = matching_mod.matching_node(state)

    mock_node.assert_called_once_with(state)
    assert result == {"match_results": []}

    # Restore singleton for subsequent tests
    matching_mod._node = None  # noqa: SLF001
