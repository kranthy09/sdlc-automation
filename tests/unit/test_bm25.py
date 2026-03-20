"""
TDD — platform/retrieval/bm25.py

Tests cover the four behaviours that matter:
  - encode()      returns (list[int], list[float]) of equal length for known terms.
  - out-of-vocab: terms absent from corpus produce an empty sparse vector.
  - ok metric:    platform_external_calls_total{status="ok"} increments on success.
  - error metric: platform_external_calls_total{status="error"} increments and
                  BM25Error is raised when encoding fails.

All tests use:
  - A fresh CollectorRegistry per test for metric isolation.
  - The _index kwarg to inject a MagicMock — no real rank-bm25 index built.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from prometheus_client import CollectorRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORPUS = ["ap invoice matching", "three way match vendor"]


def _make_retriever(mock_index: MagicMock, registry: CollectorRegistry) -> object:
    from platform.retrieval.bm25 import BM25Retriever

    return BM25Retriever(_CORPUS, registry=registry, _index=mock_index)


def _sample(registry: CollectorRegistry, labels: dict[str, str]) -> float:
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == "platform_external_calls_total" and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# encode() — structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_encode_returns_parallel_int_float_lists() -> None:
    """encode() returns (list[int], list[float]) of equal length for known terms."""
    mock_index = MagicMock()
    mock_index.idf = {"ap": 1.4, "invoice": 1.2, "matching": 1.1}

    registry = CollectorRegistry()
    bm25 = _make_retriever(mock_index, registry)

    from platform.retrieval.bm25 import BM25Retriever

    assert isinstance(bm25, BM25Retriever)
    indices, values = bm25.encode("ap invoice")  # type: ignore[attr-defined]

    assert len(indices) == len(values) == 2
    assert all(isinstance(i, int) for i in indices)
    assert all(isinstance(v, float) for v in values)


# ---------------------------------------------------------------------------
# encode() — out-of-vocabulary terms
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_encode_excludes_out_of_vocabulary_terms() -> None:
    """Terms not in the corpus vocabulary produce an empty sparse vector."""
    mock_index = MagicMock()
    mock_index.idf = {}

    registry = CollectorRegistry()
    bm25 = _make_retriever(mock_index, registry)

    indices, values = bm25.encode("payment schedule")  # type: ignore[attr-defined]

    assert indices == []
    assert values == []


# ---------------------------------------------------------------------------
# Prometheus metrics — ok path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_encode_records_ok_metric_on_success() -> None:
    """platform_external_calls_total{service=bm25,operation=encode,status=ok} == 1."""
    mock_index = MagicMock()
    mock_index.idf = {"ap": 1.4}

    registry = CollectorRegistry()
    bm25 = _make_retriever(mock_index, registry)
    bm25.encode("ap invoice")  # type: ignore[attr-defined]

    value = _sample(registry, {"service": "bm25", "operation": "encode", "status": "ok"})
    assert value == 1.0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_encode_raises_bm25_error_and_records_error_metric() -> None:
    """RuntimeError from idf lookup is wrapped in BM25Error; error metric increments."""
    mock_index = MagicMock()
    mock_index.idf = MagicMock()
    mock_index.idf.get = MagicMock(side_effect=RuntimeError("idf broken"))

    registry = CollectorRegistry()
    bm25 = _make_retriever(mock_index, registry)

    from platform.retrieval.bm25 import BM25Error

    with pytest.raises(BM25Error) as exc_info:
        bm25.encode("ap invoice")  # type: ignore[attr-defined]

    assert exc_info.value.cause is not None

    value = _sample(registry, {"service": "bm25", "operation": "encode", "status": "error"})
    assert value == 1.0
