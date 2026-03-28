"""
TDD — platform/retrieval/embedder.py

Tests cover the four behaviours that matter:
  - embed()       returns a list[float] of the correct dimension.
  - embed_batch() returns one vector per input text.
  - error:     EmbedderError is raised when the model fails.

All tests use:
  - The _model kwarg to inject a MagicMock — no real fastembed model loaded.

fastembed API note:
  TextEmbedding.embed(texts: list[str]) returns an iterable of np.ndarray,
  so mocks return a list[np.ndarray] (list is iterable, no consumption risk).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedder(mock_model: MagicMock) -> object:
    from platform.retrieval.embedder import Embedder

    return Embedder("BAAI/bge-small-en-v1.5", _model=mock_model)


# ---------------------------------------------------------------------------
# embed() — single text
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_embed_returns_float_vector_of_correct_dimension() -> None:
    """embed() converts the model's numpy array into a list[float] of length 384."""
    mock_model = MagicMock()
    mock_model.embed.return_value = [np.zeros(384, dtype=np.float32)]

    emb = _make_embedder(mock_model)

    from platform.retrieval.embedder import Embedder

    assert isinstance(emb, Embedder)
    result = emb.embed("AP invoice matching")  # type: ignore[attr-defined]

    assert isinstance(result, list)
    assert len(result) == 384
    assert all(isinstance(v, float) for v in result)
    mock_model.embed.assert_called_once_with(["AP invoice matching"])


# ---------------------------------------------------------------------------
# embed_batch() — multiple texts
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_embed_batch_returns_one_vector_per_text() -> None:
    """embed_batch() returns N vectors, one per input text, each 384-dim."""
    mock_model = MagicMock()
    mock_model.embed.return_value = [
        np.zeros(384, dtype=np.float32),
        np.zeros(384, dtype=np.float32),
        np.zeros(384, dtype=np.float32),
    ]

    emb = _make_embedder(mock_model)

    texts = ["req A", "req B", "req C"]
    result = emb.embed_batch(texts)  # type: ignore[attr-defined]

    assert len(result) == 3
    assert all(len(v) == 384 for v in result)
    mock_model.embed.assert_called_once_with(texts)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_embed_raises_embedder_error_on_failure() -> None:
    """RuntimeError from the model is wrapped in EmbedderError."""
    mock_model = MagicMock()
    mock_model.embed.side_effect = RuntimeError("CUDA OOM")

    emb = _make_embedder(mock_model)

    from platform.retrieval.embedder import EmbedderError

    with pytest.raises(EmbedderError) as exc_info:
        emb.embed("text")  # type: ignore[attr-defined]

    assert exc_info.value.cause is not None
