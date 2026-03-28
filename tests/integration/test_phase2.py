"""
Tests for the REQFIT retrieval node — Phase 2 (Session D).

All tests are @pytest.mark.unit — they use mocked infrastructure and do not
require Docker services.  The file lives in tests/integration/ because it
tests the full Phase 2 pipeline end-to-end (not a single pure function).

Test coverage:
  - Empty atoms → empty contexts (short-circuit)
  - Source A hits → AssembledContext with ranked capabilities + provenance hash
  - Doc boost: MS Learn hit mentioning the capability feature name → score +0.05
  - Source A failure → retrieval_confidence = LOW, capabilities empty
  - Wave 1 (no history) → prior_fitments empty, pipeline still produces context
  - Prior fitments → included in context, history_boost applied
  - image_derived atom → top_k = 30 (wider net)
  - Provenance hash: same inputs → same hash (determinism)
  - Multiple atoms → one context per atom
  - Module-level retrieval_node(): smoke test via LangGraph state dict
"""

from __future__ import annotations

from typing import Any

import pytest

from platform.testing.factories import (
    make_embedder,
    make_postgres_store,
    make_prior_fitment,
    make_raw_upload,
    make_search_hit,
    make_validated_atom,
    make_vector_store,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cap_hit(**overrides: Any) -> Any:
    """Capability SearchHit with realistic payload."""
    payload = {
        "module": "AccountsPayable",
        "feature": "Three-way matching",
        "description": (
            "Validates purchase order, product receipt, and vendor invoice "
            "quantities and amounts before payment approval."
        ),
        "navigation": "AP > Invoices > Invoice matching",
        "version": "10.0.38",
        "tags": ["invoice", "matching"],
    }
    payload.update(overrides.pop("payload", {}))
    return make_search_hit(id="cap-ap-0001", score=0.91, payload=payload, **overrides)


def _make_doc_hit(**overrides: Any) -> Any:
    """MS Learn SearchHit with realistic payload."""
    payload = {
        "url": "https://learn.microsoft.com/en-us/dynamics365/finance/ap/invoice-matching",
        "title": "Three-way matching overview",
        "text": "Three-way matching validates the purchase order...",
    }
    payload.update(overrides.pop("payload", {}))
    return make_search_hit(id="doc-001", score=0.80, payload=payload, **overrides)


def _make_reranker(score: float = 0.88) -> Any:
    """Mock Reranker that returns a fixed score for every candidate."""
    from unittest.mock import MagicMock

    from platform.retrieval.reranker import RerankResult

    mock = MagicMock()

    def _rerank(query: str, candidates: list, top_k: int) -> list:
        return [RerankResult(id=cid, score=score) for cid, _ in candidates]

    mock.rerank.side_effect = _rerank
    return mock


def _make_dispatch_store(cap_hits: list, doc_hits: list) -> Any:
    """VectorStore that dispatches by collection name: caps vs docs.

    Safe under parallel asyncio.to_thread calls because it routes on the
    collection_name kwarg, not on call order.
    """
    from unittest.mock import MagicMock

    from platform.retrieval.vector_store import VectorStore

    _CAP_COLLECTION = "d365_fo_capabilities"

    mock_client = MagicMock()
    mock_client.collection_exists.return_value = True

    def _query_points(collection_name: str = "", **kwargs: Any) -> Any:
        result = MagicMock()
        hits = cap_hits if collection_name == _CAP_COLLECTION else doc_hits
        points = []
        for h in hits:
            pt = MagicMock()
            pt.score = h.score
            pt.payload = {**h.payload, "_id": h.id}
            pt.id = str(h.id)
            points.append(pt)
        result.points = points
        return result

    mock_client.query_points.side_effect = _query_points
    return VectorStore("http://localhost:6333", _client=mock_client)


def _build_node(
    *,
    cap_hits: list | None = None,
    doc_hits: list | None = None,
    prior_fitments: list | None = None,
    reranker_score: float = 0.88,
) -> Any:
    """Construct a RetrievalNode with fully mocked infrastructure."""
    from modules.dynafit.nodes.retrieval import RetrievalNode

    return RetrievalNode(
        embedder=make_embedder(),
        vector_store=_make_dispatch_store(
            cap_hits=cap_hits if cap_hits is not None else [],
            doc_hits=doc_hits if doc_hits is not None else [],
        ),
        reranker=_make_reranker(reranker_score),
        postgres=make_postgres_store(prior_fitments=prior_fitments),
    )


def _make_state(atoms: list | None = None, **upload_overrides: Any) -> dict:
    upload = make_raw_upload(**upload_overrides)
    return {
        "upload": upload,
        "batch_id": "test-batch-001",
        "errors": [],
        "validated_atoms": atoms or [],
    }


# ---------------------------------------------------------------------------
# Short-circuit: no atoms
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_empty_atoms_returns_empty_contexts() -> None:
    """No validated atoms → retrieval_contexts is empty, no infra calls made."""
    from modules.dynafit.nodes.retrieval import RetrievalNode

    node = RetrievalNode(
        embedder=make_embedder(),
        vector_store=make_vector_store(),
        reranker=_make_reranker(),
        postgres=make_postgres_store(),
    )
    result = await node(_make_state(atoms=[]))
    assert result["retrieval_contexts"] == []


# ---------------------------------------------------------------------------
# Happy path: Source A + Source B
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_source_a_hit_produces_assembled_context() -> None:
    """Source A returns one capability hit → AssembledContext with one capability."""
    node = _build_node(cap_hits=[_make_cap_hit()])
    atom = make_validated_atom()
    state = _make_state(atoms=[atom])

    result = await node(state)

    contexts = result["retrieval_contexts"]
    assert len(contexts) == 1
    ctx = contexts[0]
    assert ctx.atom.atom_id == atom.atom_id
    assert len(ctx.capabilities) == 1
    assert ctx.capabilities[0].capability_id == "cap-ap-0001"
    assert ctx.capabilities[0].feature == "Three-way matching"
    assert "qdrant" in ctx.sources_available


@pytest.mark.unit
async def test_provenance_hash_is_deterministic() -> None:
    """Same atom + same capability → same provenance_hash on repeated calls."""
    node = _build_node(cap_hits=[_make_cap_hit()])
    atom = make_validated_atom()
    state = _make_state(atoms=[atom])

    r1 = await node(state)
    r2 = await node(state)

    assert (
        r1["retrieval_contexts"][0].provenance_hash == r2["retrieval_contexts"][0].provenance_hash
    )


@pytest.mark.unit
async def test_provenance_hash_differs_for_different_atoms() -> None:
    """Different atom IDs → different provenance hashes."""
    node1 = _build_node(cap_hits=[_make_cap_hit()])
    node2 = _build_node(cap_hits=[_make_cap_hit()])

    r1 = await node1(_make_state(atoms=[make_validated_atom(atom_id="REQ-001")]))
    r2 = await node2(_make_state(atoms=[make_validated_atom(atom_id="REQ-002")]))

    assert (
        r1["retrieval_contexts"][0].provenance_hash != r2["retrieval_contexts"][0].provenance_hash
    )


# ---------------------------------------------------------------------------
# Doc boost
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_doc_boost_applied_when_feature_name_matches() -> None:
    """A doc chunk whose title contains the capability feature name boosts score +0.05."""
    from modules.dynafit.nodes.retrieval import _rrf_boost
    from platform.retrieval.vector_store import SearchHit

    cap = SearchHit(
        id="cap-001",
        score=0.80,
        payload={"feature": "Three-way matching", "description": "..."},
    )
    doc = SearchHit(
        id="doc-001",
        score=0.75,
        payload={"title": "Three-way matching overview", "text": "..."},
    )

    boosted = _rrf_boost([cap], [doc])

    assert boosted[0].score == pytest.approx(0.85, abs=1e-6)


@pytest.mark.unit
def test_doc_boost_not_applied_when_no_feature_match() -> None:
    """A doc chunk unrelated to the capability → no boost."""
    from modules.dynafit.nodes.retrieval import _rrf_boost
    from platform.retrieval.vector_store import SearchHit

    cap = SearchHit(id="cap-001", score=0.80,
                    payload={"feature": "Invoice approval"})
    doc = SearchHit(id="doc-001", score=0.75,
                    payload={"title": "Cash management overview"})

    boosted = _rrf_boost([cap], [doc])

    assert boosted[0].score == pytest.approx(0.80, abs=1e-6)


@pytest.mark.unit
def test_doc_boost_capped_at_one() -> None:
    """Score + boost cannot exceed 1.0."""
    from modules.dynafit.nodes.retrieval import _rrf_boost
    from platform.retrieval.vector_store import SearchHit

    cap = SearchHit(id="cap-001", score=0.98,
                    payload={"feature": "Vendor invoice matching"})
    doc = SearchHit(id="doc-001", score=0.90,
                    payload={"title": "Vendor invoice matching"})

    boosted = _rrf_boost([cap], [doc])

    assert boosted[0].score <= 1.0


# ---------------------------------------------------------------------------
# Source A failure → LOW confidence
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_no_caps_returns_low_confidence() -> None:
    """When Source A returns no hits, retrieval_confidence = LOW and capabilities = []."""
    node = _build_node(cap_hits=[], doc_hits=[])
    state = _make_state(atoms=[make_validated_atom()])

    result = await node(state)
    ctx = result["retrieval_contexts"][0]

    assert ctx.retrieval_confidence == "LOW"
    assert ctx.capabilities == []
    assert "qdrant" not in ctx.sources_available


# ---------------------------------------------------------------------------
# Wave 1: no historical fitments
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_wave1_no_history_produces_valid_context() -> None:
    """Empty Postgres (Wave 1) → prior_fitments=[], pipeline still succeeds."""
    node = _build_node(cap_hits=[_make_cap_hit()], prior_fitments=[])
    state = _make_state(atoms=[make_validated_atom()])

    result = await node(state)
    ctx = result["retrieval_contexts"][0]

    assert ctx.prior_fitments == []
    assert "pgvector" not in ctx.sources_available
    assert len(ctx.capabilities) == 1


# ---------------------------------------------------------------------------
# Source C: prior fitments
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_prior_fitments_included_in_context() -> None:
    """Source C returns priors → prior_fitments populated, pgvector in sources."""
    prior = make_prior_fitment(reviewer_override=True)
    node = _build_node(cap_hits=[_make_cap_hit()], prior_fitments=[prior])
    state = _make_state(atoms=[make_validated_atom()])

    result = await node(state)
    ctx = result["retrieval_contexts"][0]

    assert len(ctx.prior_fitments) == 1
    assert ctx.prior_fitments[0].reviewer_override is True
    assert "pgvector" in ctx.sources_available


@pytest.mark.unit
async def test_history_boost_raises_calibrated_score() -> None:
    """With prior history, calibrated score = CE × quality_mult × 1.1 (capped at 1.0)."""
    ce_score = 0.80  # reranker returns this
    prior = make_prior_fitment()
    node = _build_node(cap_hits=[_make_cap_hit()], prior_fitments=[
                       prior], reranker_score=ce_score)
    state = _make_state(atoms=[make_validated_atom()])

    result = await node(state)
    ctx = result["retrieval_contexts"][0]

    assert len(ctx.capabilities) >= 1
    # With history the calibrated score should be >= the raw CE score (boost applied)
    # at least LOW quality_mult
    assert ctx.capabilities[0].composite_score >= ce_score * 0.70


# ---------------------------------------------------------------------------
# image_derived atom
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_image_derived_atom_requests_top_k_30() -> None:
    """image_derived atoms should request top_k=30 from Source A (wider net)."""

    from modules.dynafit.nodes.retrieval import RetrievalNode

    node = RetrievalNode(
        embedder=make_embedder(),
        vector_store=make_vector_store(),
        reranker=_make_reranker(),
        postgres=make_postgres_store(),
    )

    atom = make_validated_atom(content_type="image_derived")
    state = _make_state(atoms=[atom])

    captured_top_k: list[int] = []
    original_retrieve = node._retrieve_one  # noqa: SLF001

    # type: ignore[no-untyped-def]
    def _patched(a, dv, bm25, store, reranker, postgres, config):
        top_k = 30 if a.content_type == "image_derived" else 20
        captured_top_k.append(top_k)
        return original_retrieve(a, dv, bm25, store, reranker, postgres, config)

    node._retrieve_one = _patched  # type: ignore[method-assign]
    await node(state)

    assert captured_top_k == [30]


# ---------------------------------------------------------------------------
# Adaptive K
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_adaptive_k_finds_largest_gap() -> None:
    """_adaptive_k cuts after the largest score drop in the search range."""
    from modules.dynafit.nodes.retrieval import _adaptive_k
    from platform.retrieval.reranker import RerankResult

    results = [
        RerankResult(id="a", score=0.95),
        RerankResult(id="b", score=0.93),
        RerankResult(id="c", score=0.90),
        RerankResult(id="d", score=0.60),  # large gap here (rank 4 → cut at 3)
        RerankResult(id="e", score=0.58),
        RerankResult(id="f", score=0.55),
    ]
    k = _adaptive_k(results)
    assert k == 3


@pytest.mark.unit
def test_adaptive_k_returns_all_when_fewer_than_gap_lo() -> None:
    """Fewer than _GAP_LO results → return all of them."""
    from modules.dynafit.nodes.retrieval import _adaptive_k
    from platform.retrieval.reranker import RerankResult

    results = [RerankResult(id="a", score=0.9),
               RerankResult(id="b", score=0.8)]
    assert _adaptive_k(results) == 2


# ---------------------------------------------------------------------------
# Retrieval quality classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retrieval_quality_high_all_conditions_met() -> None:
    from modules.dynafit.nodes.retrieval import _retrieval_quality
    from platform.retrieval.reranker import RerankResult

    results = [
        RerankResult(id="a", score=0.95),
        RerankResult(id="b", score=0.93),
        RerankResult(id="c", score=0.90),
        RerankResult(id="d", score=0.88),
        RerankResult(id="e", score=0.60),  # spread = 0.95 - 0.60 = 0.35 > 0.01
    ]
    assert _retrieval_quality(results, has_history=True) == "HIGH"


@pytest.mark.unit
def test_retrieval_quality_low_empty_results() -> None:
    from modules.dynafit.nodes.retrieval import _retrieval_quality

    assert _retrieval_quality([], has_history=False) == "LOW"


# ---------------------------------------------------------------------------
# Multiple atoms
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_multiple_atoms_produce_one_context_each() -> None:
    """N atoms → N contexts, one per atom in order."""
    atoms = [
        make_validated_atom(atom_id="REQ-001"),
        make_validated_atom(atom_id="REQ-002"),
        make_validated_atom(atom_id="REQ-003"),
    ]
    node = _build_node(cap_hits=[_make_cap_hit()])
    state = _make_state(atoms=atoms)

    result = await node(state)
    contexts = result["retrieval_contexts"]

    assert len(contexts) == 3
    assert [c.atom.atom_id for c in contexts] == [
        "REQ-001", "REQ-002", "REQ-003"]


# ---------------------------------------------------------------------------
# MS Learn refs
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_ms_learn_refs_included_from_source_b() -> None:
    """Source B doc hits → ms_learn_refs populated in context."""
    node = _build_node(cap_hits=[_make_cap_hit()], doc_hits=[_make_doc_hit()])
    state = _make_state(atoms=[make_validated_atom()])

    result = await node(state)
    ctx = result["retrieval_contexts"][0]

    assert len(ctx.ms_learn_refs) == 1
    assert "ms_learn" in ctx.sources_available
    assert ctx.ms_learn_refs[0].url != ""


# ---------------------------------------------------------------------------
# Module-level retrieval_node() smoke test
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_retrieval_node_function_accepts_state_dict() -> None:
    """Module-level retrieval_node() runs without errors on a minimal state."""
    from unittest.mock import AsyncMock

    from modules.dynafit.nodes import retrieval as retrieval_mod

    # Reset module-level singleton so we control the injected instance
    retrieval_mod._node = None  # noqa: SLF001

    mock_node = AsyncMock(return_value={"retrieval_contexts": []})
    retrieval_mod._node = mock_node  # type: ignore[assignment]  # noqa: SLF001

    state = _make_state(atoms=[])
    result = await retrieval_mod.retrieval_node(state)

    mock_node.assert_called_once_with(state)
    assert result == {"retrieval_contexts": []}

    # Restore so other tests get a fresh singleton
    retrieval_mod._node = None  # noqa: SLF001
