"""
Tests for the DYNAFIT classification node — Phase 4 (Session F, part F2).

All tests are @pytest.mark.unit — they use mocked infrastructure (make_llm_client)
and do not require Docker services.  The file lives in tests/integration/ because
it tests the full Phase 4 pipeline end-to-end, not a single isolated function.

Test coverage:

  ClassificationNode.__call__:
    - Empty match_results  → empty classifications, no LLM call
    - Short-circuit (no capabilities) → auto-GAP, llm_calls_used=0
    - FAST_TRACK route     → 1 LLM call, returns FIT/PARTIAL_FIT/GAP
    - FAST_TRACK LLMError  → REVIEW_REQUIRED, llm_calls_used=0
    - GAP_CONFIRM route    → 1 LLM call, returns GAP
    - DEEP_REASON majority FIT (2/3) → FIT, llm_calls_used=3
    - DEEP_REASON majority GAP (3/3) → GAP, llm_calls_used=3
    - DEEP_REASON all-disagree (3 different) → REVIEW_REQUIRED
    - DEEP_REASON 1 success only → REVIEW_REQUIRED (not enough for majority)
    - prior_fitments surfaced in prompt via state["retrieval_contexts"]
    - Batch: 3 atoms processed independently, one per match_result
    - Sanity FIT + low composite → PARTIAL_FIT + caveats
    - Sanity GAP + high composite → REVIEW_REQUIRED + caveats
    - Module-level classification_node() smoke test (singleton reset)

Golden fixtures:
    _FIT_OUTPUT, _PARTIAL_OUTPUT, _GAP_OUTPUT represent canned LLM verdicts.
    Tests assert on classification, confidence, rationale, and route_used —
    the fields a consultant would see in the final fitment report.
"""

from __future__ import annotations

import pytest

import modules.dynafit.nodes.classification as _cls_module
from modules.dynafit.nodes.classification import (
    ClassificationNode,
    LLMClassificationOutput,
)
from platform.llm.client import LLMError
from platform.schemas.fitment import FitLabel, RouteLabel
from platform.testing.factories import (
    make_assembled_context,
    make_llm_client,
    make_match_result,
    make_prior_fitment,
    make_product_config,
    make_ranked_capability,
    make_raw_upload,
    make_validated_atom,
)

# ---------------------------------------------------------------------------
# Golden LLM output fixtures
# ---------------------------------------------------------------------------

_FIT_OUTPUT = LLMClassificationOutput(
    verdict="FIT",
    confidence=0.92,
    rationale=(
        "D365 standard three-way matching natively covers this requirement. "
        "No customisation is needed."
    ),
    d365_capability_ref="cap-ap-0001",
)

_PARTIAL_OUTPUT = LLMClassificationOutput(
    verdict="PARTIAL_FIT",
    confidence=0.78,
    rationale=(
        "D365 supports this with configuration. "
        "The matching policy must be enabled per vendor group."
    ),
    d365_capability_ref="cap-ap-0001",
    config_steps="Enable matching policy: AP > Setup > AP parameters > Invoice matching.",
)

_GAP_OUTPUT = LLMClassificationOutput(
    verdict="GAP",
    confidence=0.88,
    rationale=("D365 does not support this out-of-the-box. Custom X++ development is required."),
    gap_description="Develop X++ extension for custom approval workflow.",
)


# ---------------------------------------------------------------------------
# State builder helper
# ---------------------------------------------------------------------------


def _make_state(
    match_results: list,
    retrieval_contexts: list | None = None,
    product_id: str = "d365_fo",
) -> dict:
    return {
        "upload": make_raw_upload(product_id=product_id),
        "batch_id": "batch-phase4-test",
        "errors": [],
        "match_results": match_results,
        "retrieval_contexts": retrieval_contexts or [],
    }


# ---------------------------------------------------------------------------
# Empty / short-circuit cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_match_results_returns_empty_classifications() -> None:
    node = ClassificationNode(llm_client=make_llm_client())
    result = node(_make_state([]))
    assert result["classifications"] == []


@pytest.mark.unit
def test_shortcircuit_no_capabilities_returns_gap_without_llm_call() -> None:
    llm = make_llm_client()  # no responses configured → any call would error
    node = ClassificationNode(llm_client=llm)

    mr = make_match_result(
        ranked_capabilities=[],
        composite_scores=[],
        route=RouteLabel.GAP_CONFIRM,
        top_composite_score=0.0,
    )
    result = node(_make_state([mr]))

    [classification] = result["classifications"]
    assert classification.classification == FitLabel.GAP
    assert classification.llm_calls_used == 0
    assert "No matching D365 capability found" in classification.rationale
    llm.complete.assert_not_called()


# ---------------------------------------------------------------------------
# FAST_TRACK route
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fast_track_fit_single_call() -> None:
    node = ClassificationNode(
        llm_client=make_llm_client(_FIT_OUTPUT),
        product_config=make_product_config(),
    )
    mr = make_match_result(route=RouteLabel.FAST_TRACK, top_composite_score=0.91)
    result = node(_make_state([mr]))

    [c] = result["classifications"]
    assert c.classification == FitLabel.FIT
    assert c.confidence == 0.92
    assert c.route_used == RouteLabel.FAST_TRACK
    assert c.llm_calls_used == 1
    assert c.d365_capability_ref == "cap-ap-0001"


@pytest.mark.unit
def test_fast_track_partial_fit_single_call() -> None:
    node = ClassificationNode(
        llm_client=make_llm_client(_PARTIAL_OUTPUT),
        product_config=make_product_config(),
    )
    mr = make_match_result(route=RouteLabel.FAST_TRACK, top_composite_score=0.75)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.PARTIAL_FIT
    assert c.config_steps is not None
    assert "AP parameters" in c.config_steps


@pytest.mark.unit
def test_fast_track_llm_error_returns_review_required() -> None:
    llm = make_llm_client()
    llm.complete.side_effect = LLMError("API timeout after 3 retries")
    node = ClassificationNode(llm_client=llm, product_config=make_product_config())
    mr = make_match_result(route=RouteLabel.FAST_TRACK, top_composite_score=0.90)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.REVIEW_REQUIRED
    assert c.llm_calls_used == 0
    assert "LLM error" in c.rationale


# ---------------------------------------------------------------------------
# GAP_CONFIRM route
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_gap_confirm_gap_single_call() -> None:
    node = ClassificationNode(
        llm_client=make_llm_client(_GAP_OUTPUT),
        product_config=make_product_config(),
    )
    mr = make_match_result(route=RouteLabel.GAP_CONFIRM, top_composite_score=0.42)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.GAP
    assert c.route_used == RouteLabel.GAP_CONFIRM
    assert c.llm_calls_used == 1
    assert c.gap_description is not None


@pytest.mark.unit
def test_gap_confirm_llm_error_returns_review_required() -> None:
    llm = make_llm_client()
    llm.complete.side_effect = LLMError("rate limit")
    node = ClassificationNode(llm_client=llm, product_config=make_product_config())
    mr = make_match_result(route=RouteLabel.GAP_CONFIRM, top_composite_score=0.35)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.REVIEW_REQUIRED
    assert c.llm_calls_used == 0


# ---------------------------------------------------------------------------
# DEEP_REASON route
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_deep_reason_majority_fit_two_out_of_three() -> None:
    """2 FIT + 1 GAP → majority FIT, 3 calls used."""
    node = ClassificationNode(
        llm_client=make_llm_client(_FIT_OUTPUT, _FIT_OUTPUT, _GAP_OUTPUT),
        product_config=make_product_config(),
    )
    mr = make_match_result(route=RouteLabel.DEEP_REASON, top_composite_score=0.72)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.FIT
    assert c.llm_calls_used == 3
    assert c.route_used == RouteLabel.DEEP_REASON


@pytest.mark.unit
def test_deep_reason_unanimous_gap_three_out_of_three() -> None:
    """3/3 GAP → GAP, 3 calls used."""
    node = ClassificationNode(
        llm_client=make_llm_client(_GAP_OUTPUT, _GAP_OUTPUT, _GAP_OUTPUT),
        product_config=make_product_config(),
    )
    mr = make_match_result(route=RouteLabel.DEEP_REASON, top_composite_score=0.55)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.GAP
    assert c.llm_calls_used == 3


@pytest.mark.unit
def test_deep_reason_all_disagree_returns_review_required() -> None:
    """FIT + PARTIAL_FIT + GAP → no majority → REVIEW_REQUIRED."""
    node = ClassificationNode(
        llm_client=make_llm_client(_FIT_OUTPUT, _PARTIAL_OUTPUT, _GAP_OUTPUT),
        product_config=make_product_config(),
    )
    mr = make_match_result(route=RouteLabel.DEEP_REASON, top_composite_score=0.68)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.REVIEW_REQUIRED
    assert c.llm_calls_used == 0  # no successful majority
    assert "3 different verdicts" in c.rationale


@pytest.mark.unit
def test_deep_reason_only_one_llm_success_returns_review_required() -> None:
    """If 2/3 LLM calls fail, we can't form a majority → REVIEW_REQUIRED."""
    llm = make_llm_client(_FIT_OUTPUT)
    # first call succeeds, second and third raise LLMError
    llm.complete.side_effect = [
        _FIT_OUTPUT,
        LLMError("fail"),
        LLMError("fail"),
    ]
    node = ClassificationNode(llm_client=llm, product_config=make_product_config())
    mr = make_match_result(route=RouteLabel.DEEP_REASON, top_composite_score=0.70)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.REVIEW_REQUIRED
    assert "only 1/3" in c.rationale


# ---------------------------------------------------------------------------
# prior_fitments wired from retrieval_contexts
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prior_fitments_from_retrieval_contexts_reach_prompt() -> None:
    """render_prompt is called with prior_fitments from state["retrieval_contexts"]."""
    from unittest.mock import patch

    atom = make_validated_atom(atom_id="REQ-AP-001")
    pf = make_prior_fitment(wave=2, country="FR", classification="FIT")
    ctx = make_assembled_context(atom=atom, prior_fitments=[pf])
    mr = make_match_result(atom=atom, route=RouteLabel.FAST_TRACK, top_composite_score=0.91)

    node = ClassificationNode(
        llm_client=make_llm_client(_FIT_OUTPUT),
        product_config=make_product_config(),
    )

    rendered_prompts: list[str] = []

    original_render = _cls_module.render_prompt

    def _capture_render(name: str, **ctx_kw: object) -> str:
        rendered = original_render(name, **ctx_kw)
        rendered_prompts.append(rendered)
        return rendered

    with patch.object(_cls_module, "render_prompt", side_effect=_capture_render):
        node(_make_state([mr], retrieval_contexts=[ctx]))

    assert rendered_prompts, "render_prompt was not called"
    prompt = rendered_prompts[0]
    # prior fitment wave + country must appear in the rendered prompt
    assert 'wave="2"' in prompt
    assert 'country="FR"' in prompt


# ---------------------------------------------------------------------------
# Batch: multiple atoms
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_batch_three_atoms_processed_independently() -> None:
    """Each match_result gets its own LLM call; results appear in same order."""
    node = ClassificationNode(
        llm_client=make_llm_client(_FIT_OUTPUT, _PARTIAL_OUTPUT, _GAP_OUTPUT),
        product_config=make_product_config(),
    )

    atoms = [make_validated_atom(atom_id=f"REQ-{i:03d}") for i in range(3)]
    caps = [make_ranked_capability()]
    mrs = [
        make_match_result(
            atom=a,
            ranked_capabilities=caps,
            composite_scores=[0.91],
            route=RouteLabel.FAST_TRACK,
            top_composite_score=0.91,
        )
        for a in atoms
    ]

    result = node(_make_state(mrs))
    classifications = result["classifications"]

    assert len(classifications) == 3
    assert classifications[0].atom_id == "REQ-000"
    assert classifications[1].atom_id == "REQ-001"
    assert classifications[2].atom_id == "REQ-002"
    assert classifications[0].classification == FitLabel.FIT
    assert classifications[1].classification == FitLabel.PARTIAL_FIT
    assert classifications[2].classification == FitLabel.GAP


# ---------------------------------------------------------------------------
# Sanity checks (score-vs-verdict consistency)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sanity_fit_with_low_composite_demoted_to_partial_fit() -> None:
    """FIT verdict on composite=0.40 is implausible → demote to PARTIAL_FIT."""
    node = ClassificationNode(
        llm_client=make_llm_client(_FIT_OUTPUT),
        product_config=make_product_config(),
    )
    # composite below _FIT_SANITY_MIN (0.50)
    mr = make_match_result(route=RouteLabel.FAST_TRACK, top_composite_score=0.40)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.PARTIAL_FIT
    assert c.caveats is not None
    assert "Demoted to PARTIAL_FIT" in c.caveats


@pytest.mark.unit
def test_sanity_gap_with_high_composite_flagged_for_review() -> None:
    """GAP verdict on composite=0.91 is suspicious → REVIEW_REQUIRED."""
    cfg = make_product_config(fit_confidence_threshold=0.85)
    node = ClassificationNode(
        llm_client=make_llm_client(_GAP_OUTPUT),
        product_config=cfg,
    )
    # composite above fit_confidence_threshold (0.85)
    mr = make_match_result(route=RouteLabel.GAP_CONFIRM, top_composite_score=0.91)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.REVIEW_REQUIRED
    assert c.caveats is not None
    assert "Possible LLM error" in c.caveats


@pytest.mark.unit
def test_sanity_gap_with_moderate_composite_not_flagged() -> None:
    """GAP on composite=0.55 is consistent — no sanity override."""
    node = ClassificationNode(
        llm_client=make_llm_client(_GAP_OUTPUT),
        product_config=make_product_config(),
    )
    mr = make_match_result(route=RouteLabel.GAP_CONFIRM, top_composite_score=0.55)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.GAP
    assert c.caveats is None


@pytest.mark.unit
def test_sanity_fit_with_adequate_composite_not_demoted() -> None:
    """FIT on composite=0.75 is above sanity floor — no override."""
    node = ClassificationNode(
        llm_client=make_llm_client(_FIT_OUTPUT),
        product_config=make_product_config(),
    )
    mr = make_match_result(route=RouteLabel.FAST_TRACK, top_composite_score=0.75)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.classification == FitLabel.FIT
    assert c.caveats is None


# ---------------------------------------------------------------------------
# Atom metadata preserved in ClassificationResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_atom_fields_preserved_in_classification_result() -> None:
    atom = make_validated_atom(
        atom_id="REQ-GL-007",
        module="GeneralLedger",
        country="FR",
        wave=3,
    )
    node = ClassificationNode(
        llm_client=make_llm_client(_FIT_OUTPUT),
        product_config=make_product_config(),
    )
    mr = make_match_result(atom=atom, route=RouteLabel.FAST_TRACK, top_composite_score=0.91)
    [c] = node(_make_state([mr]))["classifications"]

    assert c.atom_id == "REQ-GL-007"
    assert c.module == "GeneralLedger"
    assert c.country == "FR"
    assert c.wave == 3


# ---------------------------------------------------------------------------
# Module-level singleton smoke test
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_module_level_classification_node_smoke() -> None:
    """classification_node() creates a singleton; calling it returns classifications."""
    # Reset singleton so the test gets a fresh one
    _cls_module._node = None

    # Patch LLMClient so no real API call is made
    from unittest.mock import MagicMock, patch

    mock_client = MagicMock()
    mock_client.complete.return_value = _FIT_OUTPUT

    with patch(
        "modules.dynafit.nodes.classification.LLMClient",
        return_value=mock_client,
    ):
        mr = make_match_result(route=RouteLabel.FAST_TRACK, top_composite_score=0.91)
        result = _cls_module.classification_node(_make_state([mr]))

    assert len(result["classifications"]) == 1
    # Clean up so other tests are not affected
    _cls_module._node = None
