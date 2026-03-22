"""
TDD — platform/retrieval/reranker.py

Tests cover the four behaviours that matter:
  - rerank()      returns RerankResult list sorted descending, scores sigmoid'd to [0, 1].
  - top_k:        result list is capped at top_k entries.
  - ok metric:    platform_external_calls_total{status="ok"} increments on success.
  - error metric: platform_external_calls_total{status="error"} increments and
                  RerankerError is raised when the model fails.

All tests use:
  - A fresh CollectorRegistry per test for metric isolation.
  - The _model kwarg to inject a MagicMock — no real TextCrossEncoder loaded.

fastembed API note:
  TextCrossEncoder.rerank(query, documents) returns an Iterable[float] of raw
  logits in document order. The implementation applies sigmoid to normalise to
  [0, 1], so mock return values use raw logit floats (same as before).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from prometheus_client import CollectorRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
_CANDIDATES: list[tuple[str | int, str]] = [
    ("cap-1", "AP invoice three-way matching"),
    ("cap-2", "Vendor payment terms configuration"),
    ("cap-3", "Purchase order approval workflow"),
]


def _make_reranker(mock_model: MagicMock, registry: CollectorRegistry) -> object:
    from platform.retrieval.reranker import Reranker

    return Reranker(_MODEL, registry=registry, _model=mock_model)


def _sample(registry: CollectorRegistry, labels: dict[str, str]) -> float:
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == "platform_external_calls_total" and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# rerank() — sorted sigmoid scores
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rerank_returns_sorted_results_with_sigmoid_scores() -> None:
    """rerank() returns RerankResult list: scores in [0,1], sorted descending, IDs preserved."""
    mock_model = MagicMock()
    # logits: cap-1=2.0 (highest), cap-2=-1.0 (lowest), cap-3=0.5 (middle)
    mock_model.rerank.return_value = [2.0, -1.0, 0.5]

    registry = CollectorRegistry()
    reranker = _make_reranker(mock_model, registry)

    from platform.retrieval.reranker import Reranker, RerankResult

    assert isinstance(reranker, Reranker)
    results = reranker.rerank("AP invoice matching", _CANDIDATES, top_k=3)  # type: ignore[attr-defined]

    assert len(results) == 3
    assert all(isinstance(r, RerankResult) for r in results)
    assert all(0.0 <= r.score <= 1.0 for r in results)
    # scores must be descending
    assert results[0].score >= results[1].score >= results[2].score
    # cap-1 had the highest logit (2.0) → must be first
    assert results[0].id == "cap-1"
    mock_model.rerank.assert_called_once_with(
        "AP invoice matching",
        [
            "AP invoice three-way matching",
            "Vendor payment terms configuration",
            "Purchase order approval workflow",
        ],
    )


# ---------------------------------------------------------------------------
# rerank() — top_k capping
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rerank_respects_top_k() -> None:
    """rerank() returns at most top_k results even when more candidates are provided."""
    mock_model = MagicMock()
    mock_model.rerank.return_value = [2.0, -1.0, 0.5]

    registry = CollectorRegistry()
    reranker = _make_reranker(mock_model, registry)

    results = reranker.rerank("AP invoice matching", _CANDIDATES, top_k=2)  # type: ignore[attr-defined]

    assert len(results) == 2


# ---------------------------------------------------------------------------
# Prometheus metrics — ok path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rerank_records_ok_metric_on_success() -> None:
    """platform_external_calls_total{service=reranker,operation=rerank,status=ok} == 1."""
    mock_model = MagicMock()
    mock_model.rerank.return_value = [1.0, 0.0]

    registry = CollectorRegistry()
    reranker = _make_reranker(mock_model, registry)
    reranker.rerank("query", [("a", "text a"), ("b", "text b")], top_k=2)  # type: ignore[attr-defined]

    value = _sample(registry, {"service": "reranker", "operation": "rerank", "status": "ok"})
    assert value == 1.0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rerank_raises_reranker_error_and_records_error_metric() -> None:
    """RuntimeError from rerank is wrapped in RerankerError; error metric increments."""
    mock_model = MagicMock()
    mock_model.rerank.side_effect = RuntimeError("CUDA OOM")

    registry = CollectorRegistry()
    reranker = _make_reranker(mock_model, registry)

    from platform.retrieval.reranker import RerankerError

    with pytest.raises(RerankerError) as exc_info:
        reranker.rerank("query", [("x", "some text")], top_k=1)  # type: ignore[attr-defined]

    assert exc_info.value.cause is not None

    value = _sample(registry, {"service": "reranker", "operation": "rerank", "status": "error"})
    assert value == 1.0
