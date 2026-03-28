"""
TDD — platform/retrieval/bm25.py

Tests cover the four behaviours that matter:
  - encode()      returns (list[int], list[float]) of equal length for known terms.
  - out-of-vocab: terms absent from corpus produce an empty sparse vector.
  - error:     BM25Error is raised when encoding fails.

All tests use:
  - The _index kwarg to inject a MagicMock — no real rank-bm25 index built.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORPUS = ["ap invoice matching", "three way match vendor"]


def _make_retriever(mock_index: MagicMock) -> object:
    from platform.retrieval.bm25 import BM25Retriever

    return BM25Retriever(_CORPUS, _index=mock_index)


# ---------------------------------------------------------------------------
# encode() — structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_encode_returns_parallel_int_float_lists() -> None:
    """encode() returns (list[int], list[float]) of equal length for known terms."""
    mock_index = MagicMock()
    mock_index.idf = {"ap": 1.4, "invoice": 1.2, "matching": 1.1}

    bm25 = _make_retriever(mock_index)

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

    bm25 = _make_retriever(mock_index)

    indices, values = bm25.encode("payment schedule")  # type: ignore[attr-defined]

    assert indices == []
    assert values == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_encode_raises_bm25_error_on_failure() -> None:
    """RuntimeError from idf lookup is wrapped in BM25Error."""
    mock_index = MagicMock()
    mock_index.idf = MagicMock()
    mock_index.idf.get = MagicMock(side_effect=RuntimeError("idf broken"))

    bm25 = _make_retriever(mock_index)

    from platform.retrieval.bm25 import BM25Error

    with pytest.raises(BM25Error) as exc_info:
        bm25.encode("ap invoice")  # type: ignore[attr-defined]

    assert exc_info.value.cause is not None
