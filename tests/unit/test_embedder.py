"""
TDD — platform/retrieval/embedder.py

Tests cover the four behaviours that matter:
  - embed()       returns a list[float] of the correct dimension.
  - embed_batch() returns one vector per input text.
  - ok metric:    platform_external_calls_total{status="ok"} increments on success.
  - error metric: platform_external_calls_total{status="error"} increments and
                  EmbedderError is raised when the model fails.

All tests use:
  - A fresh CollectorRegistry per test for metric isolation.
  - The _model kwarg to inject a MagicMock — no real fastembed model loaded.

fastembed API note:
  TextEmbedding.embed(texts: list[str]) returns an iterable of np.ndarray,
  so mocks return a list[np.ndarray] (list is iterable, no consumption risk).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from prometheus_client import CollectorRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedder(mock_model: MagicMock, registry: CollectorRegistry) -> object:
    from platform.retrieval.embedder import Embedder

    return Embedder("BAAI/bge-small-en-v1.5", registry=registry, _model=mock_model)


def _sample(registry: CollectorRegistry, labels: dict[str, str]) -> float:
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == "platform_external_calls_total" and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# embed() — single text
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_embed_returns_float_vector_of_correct_dimension() -> None:
    """embed() converts the model's numpy array into a list[float] of length 384."""
    mock_model = MagicMock()
    mock_model.embed.return_value = [np.zeros(384, dtype=np.float32)]

    registry = CollectorRegistry()
    emb = _make_embedder(mock_model, registry)

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

    registry = CollectorRegistry()
    emb = _make_embedder(mock_model, registry)

    texts = ["req A", "req B", "req C"]
    result = emb.embed_batch(texts)  # type: ignore[attr-defined]

    assert len(result) == 3
    assert all(len(v) == 384 for v in result)
    mock_model.embed.assert_called_once_with(texts)


# ---------------------------------------------------------------------------
# Prometheus metrics — ok path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_embed_records_ok_metric_on_success() -> None:
    """platform_external_calls_total{service=embedder,operation=encode,status=ok} == 1."""
    mock_model = MagicMock()
    mock_model.embed.return_value = [np.zeros(384, dtype=np.float32)]

    registry = CollectorRegistry()
    emb = _make_embedder(mock_model, registry)
    emb.embed("hello")  # type: ignore[attr-defined]

    value = _sample(registry, {"service": "embedder", "operation": "encode", "status": "ok"})
    assert value == 1.0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_embed_raises_embedder_error_and_records_error_metric() -> None:
    """RuntimeError from the model is wrapped in EmbedderError; error metric increments."""
    mock_model = MagicMock()
    mock_model.embed.side_effect = RuntimeError("CUDA OOM")

    registry = CollectorRegistry()
    emb = _make_embedder(mock_model, registry)

    from platform.retrieval.embedder import EmbedderError

    with pytest.raises(EmbedderError) as exc_info:
        emb.embed("text")  # type: ignore[attr-defined]

    assert exc_info.value.cause is not None

    value = _sample(registry, {"service": "embedder", "operation": "encode", "status": "error"})
    assert value == 1.0
