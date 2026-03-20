"""
Cross-encoder reranker — wraps sentence-transformers CrossEncoder for
query-document relevance scoring.

Scores (query, document) pairs with a cross-encoder model, applies sigmoid
to convert raw logits to [0, 1] scores, and returns top-k candidates sorted
by descending relevance.

Every rerank call is wrapped in record_call("reranker", "rerank") for Prometheus.

Usage:
    from platform.retrieval.reranker import Reranker

    reranker = Reranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
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

from prometheus_client import CollectorRegistry

from platform.observability.logger import get_logger
from platform.observability.metrics import MetricsRecorder

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
        model_name: HuggingFace model ID (e.g. "cross-encoder/ms-marco-MiniLM-L-6-v2").
        registry:   Prometheus CollectorRegistry for metric isolation in tests.
        _model:     Pre-loaded model instance — for testing only; skips lazy load.
    """

    def __init__(
        self,
        model_name: str,
        *,
        registry: CollectorRegistry | None = None,
        _model: Any = None,
    ) -> None:
        self._model_name = model_name
        self._recorder = MetricsRecorder(registry)
        self._model: Any = _model

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415

            log.info("reranker_load_model", model=self._model_name)
            self._model = CrossEncoder(self._model_name)
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
            RerankerError: If the model fails to load or predict.
        """
        if not candidates:
            return []
        try:
            with self._recorder.record_call("reranker", "rerank"):
                pairs = [(query, text) for _, text in candidates]
                raw: Any = self._get_model().predict(pairs)
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
