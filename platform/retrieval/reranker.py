"""
Cross-encoder reranker — wraps fastembed TextCrossEncoder for
query-document relevance scoring.

fastembed uses ONNX Runtime instead of PyTorch — ~50 MB install vs ~500 MB.
Model weights are downloaded on first use to fastembed's cache directory.

Scores documents against a query with a cross-encoder model, applies sigmoid
to convert raw logits to [0, 1] scores, and returns top-k candidates sorted
by descending relevance.

Usage:
    from platform.retrieval.reranker import Reranker

    reranker = Reranker("Xenova/ms-marco-MiniLM-L-6-v2")
    results = reranker.rerank(
        query="AP invoice three-way matching",
        candidates=[("cap-001", "Three-way matching..."), ("cap-002", "Vendor invoices...")],
        top_k=10,
    )
    # results: list[RerankResult] sorted by score descending, score in [0, 1]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from platform.observability.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class RerankerError(Exception):
    """Raised when reranking fails — model load error or predict failure."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class RerankResult:
    """A single reranked candidate.

    Attributes:
        id:    Caller-supplied ID (passed through from candidates).
        score: sigmoid(logit) in [0, 1] — higher means more relevant.
    """

    id: str | int
    score: float


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------


class Reranker:
    """Cross-encoder reranker backed by sentence-transformers.

    The underlying CrossEncoder is loaded lazily on the first rerank call so
    that importing this module never triggers the model download.

    Args:
        model_name: fastembed model ID (e.g. "Xenova/ms-marco-MiniLM-L-6-v2").
        _model:     Pre-loaded model instance — for testing only; skips lazy load.
    """

    def __init__(
        self,
        model_name: str,
        *,
        _model: Any = None,
    ) -> None:
        self._model_name = model_name
        self._model: Any = _model

    def _get_model(self) -> Any:
        if self._model is None:
            # tqdm's threading lock does not survive Celery's ForkPoolWorker
            # fork(). Reinitialize it before loading the model to prevent
            # "type object 'tqdm' has no attribute '_lock'" in child workers.
            import tqdm.std  # noqa: PLC0415
            if not hasattr(tqdm.std.tqdm, "_lock"):
                tqdm.std.tqdm._lock = tqdm.std.TRLock()

            from fastembed.rerank.cross_encoder.text_cross_encoder import (
                TextCrossEncoder,  # noqa: PLC0415, E501
            )

            log.info("reranker_load_model", model=self._model_name)
            self._model = TextCrossEncoder(self._model_name)
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[tuple[str | int, str]],
        top_k: int,
    ) -> list[RerankResult]:
        """Score and sort candidates by relevance to query.

        Args:
            query:      The search query or requirement text.
            candidates: List of (id, text) pairs to score against the query.
            top_k:      Maximum number of results to return.

        Returns:
            Up to top_k RerankResult objects sorted by descending score.

        Raises:
            RerankerError: If the model fails to load or score.
        """
        if not candidates:
            return []
        try:
            docs = [text for _, text in candidates]
            raw: list[Any] = list(self._get_model().rerank(query, docs))
            results = [
                RerankResult(id=cid, score=_sigmoid(float(logit)))
                for (cid, _), logit in zip(candidates, raw, strict=True)
            ]
            results.sort(key=lambda r: r.score, reverse=True)
            top = results[:top_k]
            log.debug(
                "reranker_rerank",
                model=self._model_name,
                n_candidates=len(candidates),
                top_k=top_k,
                returned=len(top),
            )
            return top
        except RerankerError:
            raise
        except Exception as exc:
            raise RerankerError(
                f"rerank failed (model={self._model_name!r}): {exc}", cause=exc
            ) from exc


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _sigmoid(x: float) -> float:
    """Map a logit to a probability in [0, 1]."""
    return 1.0 / (1.0 + math.exp(-x))
