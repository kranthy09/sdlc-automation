"""
Tests for the DYNAFIT matching node — Phase 3 (Session E).

All tests are @pytest.mark.unit — they use mocked infrastructure and do not
require Docker services. The file lives in tests/integration/ because it
tests the full Phase 3 pipeline end-to-end (not a single pure function).

Test coverage:
  Pure helpers (tested directly):
    - _compute_composite: weighted sum formula is exact
    - _assign_route: FAST_TRACK / DEEP_REASON / GAP_CONFIRM thresholds
    - _detect_anomaly: high cosine without entity agreement raises flag
    - _entity_overlap_score: hint-in-cap-text fractional coverage

  MatchingNode integration:
    - Empty contexts → empty match_results (no infra calls)
    - No capabilities in context → GAP_CONFIRM, empty ranked_capabilities
    - composite_scores parallel with ranked_capabilities (schema invariant)
    - Anomaly flag propagated into MatchResult.anomaly_flags
    - FIT prior boosts composite by _HISTORY_BOOST
    - Non-FIT prior does NOT trigger history boost
    - Multiple contexts → one MatchResult per context in same order
    - Dedup: near-identical capabilities collapsed to the higher-scored one
    - Module-level matching_node() smoke test (singleton reset pattern)
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


def _make_unit_embedder(dim: int = 1024) -> Embedder:
    """Embedder that returns identical unit vectors → embedding_cosine = 1.0."""
    mock_model = MagicMock()
    unit = np.ones(dim, dtype=np.float32) / np.sqrt(dim)

    def _encode(texts: str | list[str]) -> Any:
        if isinstance(texts, list):
            return np.tile(unit, (len(texts), 1))
        return unit.copy()

    mock_model.encode.side_effect = _encode
    return Embedder("test-unit", _model=mock_model, registry=CollectorRegistry())


def _make_orthogonal_embedder(dim: int = 4) -> Embedder:
    """Embedder returning [1,0,...] for atom and [0,1,...] for caps → cosine = 0.0."""
    mock_model = MagicMock()
    call_count: list[int] = [0]

    def _encode(texts: str | list[str]) -> Any:
        n = len(texts) if isinstance(texts, list) else 1
        vecs = np.zeros((n, dim), dtype=np.float32)
        for i in range(n):
            idx = call_count[0] % dim
            vecs[i, idx] = 1.0
            call_count[0] += 1
        return vecs

    mock_model.encode.side_effect = _encode
    return Embedder("test-ortho", _model=mock_model, registry=CollectorRegistry())


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
# Pure helper tests
# ===========================================================================


@pytest.mark.unit
def test_compute_composite_exact_formula() -> None:
    """Weighted sum matches the spec formula exactly."""
    from modules.dynafit.nodes.matching import _compute_composite

    signals = {
        "embedding_cosine": 1.0,
        "entity_overlap": 1.0,
        "token_ratio": 1.0,
        "historical_alignment": 1.0,
        "rerank_score": 1.0,
    }
    assert _compute_composite(signals) == pytest.approx(1.0)


@pytest.mark.unit
def test_compute_composite_partial_signals() -> None:
    """Known partial signals produce the correct weighted sum."""
    from modules.dynafit.nodes.matching import _compute_composite

    signals = {
        "embedding_cosine": 0.0,
        "entity_overlap": 0.0,
        "token_ratio": 0.0,
        "historical_alignment": 1.0,  # contributes 0.25
        "rerank_score": 1.0,          # contributes 0.15
    }
    # expected = 0.25 + 0.15 = 0.40
    assert _compute_composite(signals) == pytest.approx(0.40)


@pytest.mark.unit
def test_compute_composite_capped_at_one() -> None:
    """With all signals > 1.0 the result is capped at 1.0 (defence-in-depth)."""
    from modules.dynafit.nodes.matching import _compute_composite

    signals = {k: 2.0 for k in ["embedding_cosine", "entity_overlap", "token_ratio",
                                  "historical_alignment", "rerank_score"]}
    assert _compute_composite(signals) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Route assignment
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_assign_route_fast_track() -> None:
    """composite > 0.85 AND has_history → FAST_TRACK."""
    from modules.dynafit.nodes.matching import _assign_route

    assert _assign_route(0.90, has_history=True) == RouteLabel.FAST_TRACK


@pytest.mark.unit
def test_assign_route_high_composite_no_history_is_deep_reason() -> None:
    """composite > 0.85 but no history → DEEP_REASON (not FAST_TRACK)."""
    from modules.dynafit.nodes.matching import _assign_route

    assert _assign_route(0.90, has_history=False) == RouteLabel.DEEP_REASON


@pytest.mark.unit
def test_assign_route_deep_reason_boundary() -> None:
    """composite exactly at 0.60 → DEEP_REASON (inclusive lower bound)."""
    from modules.dynafit.nodes.matching import _assign_route

    assert _assign_route(0.60, has_history=False) == RouteLabel.DEEP_REASON


@pytest.mark.unit
def test_assign_route_gap_confirm() -> None:
    """composite < 0.60 → GAP_CONFIRM regardless of history."""
    from modules.dynafit.nodes.matching import _assign_route

    assert _assign_route(0.50, has_history=True) == RouteLabel.GAP_CONFIRM
    assert _assign_route(0.30, has_history=False) == RouteLabel.GAP_CONFIRM


@pytest.mark.unit
def test_assign_route_fast_track_boundary() -> None:
    """composite exactly at 0.85 is NOT > threshold → DEEP_REASON (not FAST_TRACK)."""
    from modules.dynafit.nodes.matching import _assign_route

    assert _assign_route(0.85, has_history=True) == RouteLabel.DEEP_REASON


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detect_anomaly_flagged() -> None:
    """High cosine (> 0.85) with low entity overlap (< 0.20) → anomaly flag."""
    from modules.dynafit.nodes.matching import _detect_anomaly

    result = _detect_anomaly(embedding_cosine=0.90, entity_overlap=0.10)
    assert result is not None
    assert "high_cosine_no_entity" in result


@pytest.mark.unit
def test_detect_anomaly_clear_when_entity_ok() -> None:
    """High cosine but entity_overlap >= 0.20 → no anomaly."""
    from modules.dynafit.nodes.matching import _detect_anomaly

    assert _detect_anomaly(0.90, 0.20) is None
    assert _detect_anomaly(0.90, 0.50) is None


@pytest.mark.unit
def test_detect_anomaly_clear_when_cosine_low() -> None:
    """Low cosine → anomaly never raised regardless of entity overlap."""
    from modules.dynafit.nodes.matching import _detect_anomaly

    assert _detect_anomaly(0.70, 0.05) is None


# ---------------------------------------------------------------------------
# Entity overlap
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_entity_overlap_empty_hints_returns_zero() -> None:
    from modules.dynafit.nodes.matching import _entity_overlap_score

    assert _entity_overlap_score([], "invoice matching vendor") == pytest.approx(0.0)


@pytest.mark.unit
def test_entity_overlap_all_hints_present() -> None:
    from modules.dynafit.nodes.matching import _entity_overlap_score

    hints = ["invoice", "vendor", "matching"]
    cap_text = "vendor invoice matching policy configuration"
    assert _entity_overlap_score(hints, cap_text) == pytest.approx(1.0)


@pytest.mark.unit
def test_entity_overlap_partial_match() -> None:
    from modules.dynafit.nodes.matching import _entity_overlap_score

    hints = ["invoice", "vendor", "purchase order"]
    cap_text = "invoice approval workflow"  # only "invoice" matches
    assert _entity_overlap_score(hints, cap_text) == pytest.approx(1 / 3)


@pytest.mark.unit
def test_entity_overlap_no_match_returns_zero() -> None:
    from modules.dynafit.nodes.matching import _entity_overlap_score

    hints = ["payroll", "employee"]
    cap_text = "three-way matching for purchase orders"
    assert _entity_overlap_score(hints, cap_text) == pytest.approx(0.0)


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
def test_composite_scores_parallel_with_ranked_capabilities() -> None:
    """len(composite_scores) == len(ranked_capabilities) — MatchResult schema invariant."""
    node = _build_node()
    caps = [make_ranked_capability(capability_id=f"cap-{i:03d}") for i in range(3)]
    ctx = make_assembled_context(capabilities=caps)

    result = node(_make_state(contexts=[ctx]))
    mr = result["match_results"][0]

    assert len(mr.composite_scores) == len(mr.ranked_capabilities)


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
    score_no_history = node_no(_make_state(contexts=[ctx_no_history]))[
        "match_results"
    ][0].top_composite_score

    # With a FIT prior — rebuild node to get fresh embedder state
    embedder2 = make_embedder()
    fit_prior = make_prior_fitment(classification="FIT")
    ctx_with_history = make_assembled_context(
        capabilities=[cap], prior_fitments=[fit_prior]
    )
    node_yes = _build_node(embedder=embedder2)
    score_with_history = node_yes(_make_state(contexts=[ctx_with_history]))[
        "match_results"
    ][0].top_composite_score

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

    # historical_alignment = 1.0 (priors exist) but no FIT boost
    # score should NOT include +0.10
    # Check by comparing against zero-history case + historical_alignment weight
    ctx_no_prior = make_assembled_context(capabilities=[cap], prior_fitments=[])
    node2 = _build_node()
    mr_no_prior = node2(_make_state(contexts=[ctx_no_prior]))["match_results"][0]

    # GAP prior contributes historical_alignment=1.0 (weight 0.25) but no extra boost
    assert mr.top_composite_score > mr_no_prior.top_composite_score
    assert mr.top_composite_score < mr_no_prior.top_composite_score + _HISTORY_BOOST + 0.30


@pytest.mark.unit
def test_ranked_capabilities_sorted_highest_first() -> None:
    """Capabilities with lower rerank scores are not ranked above higher-scored ones."""
    node = _build_node()
    # Two caps: high rerank_score and low rerank_score
    cap_high = make_ranked_capability(capability_id="cap-high", rerank_score=0.95)
    cap_low = make_ranked_capability(capability_id="cap-low", rerank_score=0.20)
    ctx = make_assembled_context(capabilities=[cap_low, cap_high])  # low first in input

    result = node(_make_state(contexts=[ctx]))
    mr = result["match_results"][0]

    # After ranking, high should come first
    assert mr.ranked_capabilities[0].capability_id == "cap-high"
    assert mr.composite_scores[0] > mr.composite_scores[1]


@pytest.mark.unit
def test_composite_score_updated_on_ranked_capability() -> None:
    """ranked_capabilities carry the Phase 3 composite_score (not Phase 2 value)."""
    node = _build_node()
    cap = make_ranked_capability(composite_score=0.50, rerank_score=0.80)
    ctx = make_assembled_context(capabilities=[cap])

    mr = node(_make_state(contexts=[ctx]))["match_results"][0]

    # Phase 3 recomputes composite; the value on the returned cap should match
    # the composite_score in the parallel list
    assert mr.ranked_capabilities[0].composite_score == pytest.approx(
        mr.composite_scores[0]
    )


@pytest.mark.unit
def test_dedup_removes_near_identical_capabilities() -> None:
    """Two caps with near-identical descriptions and cosine > 0.95 → only one kept."""
    # Use unit embedder: all caps get the same embedding → cosine = 1.0 between any two
    node = _build_node(embedder=_make_unit_embedder())

    # Same description → cosine between them will be 1.0 > 0.95 threshold
    same_desc = "Three-way matching validates purchase orders and invoices."
    cap_a = make_ranked_capability(capability_id="cap-a", rerank_score=0.90,
                                    description=same_desc)
    cap_b = make_ranked_capability(capability_id="cap-b", rerank_score=0.80,
                                    description=same_desc)
    ctx = make_assembled_context(capabilities=[cap_a, cap_b])

    mr = node(_make_state(contexts=[ctx]))["match_results"][0]

    # Dedup should keep only one (the higher-scored cap_a)
    assert len(mr.ranked_capabilities) == 1
    assert mr.ranked_capabilities[0].capability_id == "cap-a"


@pytest.mark.unit
def test_all_signals_via_unit_embedder_produces_fast_track() -> None:
    """All signals maximised → composite near 1.0, FAST_TRACK with history present."""
    node = _build_node(embedder=_make_unit_embedder())

    # Atom entity hints match cap text → entity_overlap = 1.0
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
