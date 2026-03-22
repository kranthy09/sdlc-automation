"""
BM25 sparse vector encoder — wraps rank-bm25 for hybrid Qdrant search.

Converts text to a sparse (term-index, IDF-weight) vector compatible with
Qdrant's sparse vector field. Used alongside dense embeddings for hybrid RRF
retrieval.

Usage:
    from platform.retrieval.bm25 import BM25Retriever

    # Build once from your document corpus:
    retriever = BM25Retriever(corpus=["AP invoice matching", ...])

    # Encode at index time (document sparse vector):
    indices, values = retriever.encode("AP invoice matching")
    store.upsert("collection", [
        Point(id="doc-1", dense_vector=[...], sparse_indices=indices, sparse_values=values)
    ])

    # Encode at query time (query sparse vector):
    q_indices, q_values = retriever.encode(query_text)
    hits = store.search("collection", query_vec, top_k=20, sparse=(q_indices, q_values))
"""

from __future__ import annotations

from typing import Any

from platform.observability.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class BM25Error(Exception):
    """Raised when BM25 encoding fails."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)


# ---------------------------------------------------------------------------
# BM25Retriever
# ---------------------------------------------------------------------------


class BM25Retriever:
    """BM25 sparse vector encoder backed by rank-bm25.

    Builds a term vocabulary from a corpus then encodes any text to a sparse
    (term_indices, idf_weights) vector for Qdrant hybrid search.

    Args:
        corpus:   Documents used to build vocabulary and IDF weights.
        _index:   Pre-built BM25Okapi index — for testing only; bypasses build.
    """

    def __init__(
        self,
        corpus: list[str],
        *,
        _index: Any = None,
    ) -> None:
        tokenized = [_tokenize(doc) for doc in corpus]
        self._vocab: dict[str, int] = _build_vocab(tokenized)
        self._index: Any = _index if _index is not None else _build_index(tokenized)

    def encode(self, text: str) -> tuple[list[int], list[float]]:
        """Encode text to a sparse (indices, values) vector.

        Only terms present in the corpus vocabulary are included. Weights are
        BM25 IDF scores — zero-IDF terms are skipped.

        Args:
            text: Query or document text to encode.

        Returns:
            Tuple of (term_indices, idf_weights) — parallel lists, same length.

        Raises:
            BM25Error: If encoding fails for any reason.
        """
        try:
            tokens = _tokenize(text)
            indices: list[int] = []
            values: list[float] = []
            seen: set[str] = set()
            for token in tokens:
                if token in self._vocab and token not in seen:
                    seen.add(token)
                    idf = float(self._index.idf.get(token, 0.0))
                    if idf > 0.0:
                        indices.append(self._vocab[token])
                        values.append(idf)
            log.debug("bm25_encode", n_terms=len(indices))
            return indices, values
        except BM25Error:
            raise
        except Exception as exc:
            raise BM25Error(f"encode failed: {exc}", cause=exc) from exc


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase whitespace tokenization."""
    return text.lower().split()


def _build_vocab(tokenized: list[list[str]]) -> dict[str, int]:
    """Build a term→index vocabulary from pre-tokenized documents."""
    vocab: dict[str, int] = {}
    for tokens in tokenized:
        for token in tokens:
            if token not in vocab:
                vocab[token] = len(vocab)
    return vocab


def _build_index(tokenized: list[list[str]]) -> Any:
    """Build a BM25Okapi index from pre-tokenized documents."""
    from rank_bm25 import BM25Okapi  # noqa: PLC0415

    return BM25Okapi(tokenized)
