from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from platforms.retrieval.embedder import embed
from platforms.retrieval.retriever import search
from platforms.schemas.retrieval import (
    RetrievalQuery,
    RetrievalResponse,
    RetrievedChunk,
)


class _ScoredPointLike(Protocol):
    """Minimal shape we need from the retriever results.

    This avoids importing/depending on Qdrant types directly in the agent layer.
    """

    score: float
    payload: dict[str, Any] | None


def _extract_text_from_payload(payload: Mapping[str, Any] | None) -> str:
    """Convert a Qdrant payload into the `RetrievedChunk.text` field.

    Expected (from your DYNAFIT spec) common keys:
      - MS Learn chunks: `text`
    Sometimes you may store other payload fields (e.g. capability `description`),
    so we provide a small fallback ladder.
    """
    if not payload:
        return ""

    # Primary: MS Learn chunk payload
    value = payload.get("text")
    if isinstance(value, str) and value.strip():
        return value.strip()

    # Fallback: capability-like records
    value = payload.get("description")
    if isinstance(value, str) and value.strip():
        return value.strip()

    # Last resort: avoid returning non-string garbage
    return ""


def rag_retrieval_node(query: RetrievalQuery) -> RetrievalResponse:
    """Phase 2 retrieval node.

    Input:
      - RetrievalQuery (validated by Pydantic)

    Steps:
      1. Generate embedding (via platform embedding module)
       2. Call retriever (platform Qdrant adapter; no direct Qdrant here)
      3. Convert raw results to RetrievedChunk
      4. Return RetrievalResponse
    """
    # 1) Generate embedding
    vector = embed(query.query)

    # 2) Call retriever (raw results come back as "scored points")
    raw_results = search(vector=vector, top_k=query.top_k)

    # 3) Convert results into RetrievedChunk
    chunks: list[RetrievedChunk] = []
    for r in raw_results:
        # Treat `r` as the minimal scored-point interface we expect.
        # (The retriever is responsible for returning Qdrant-shaped objects.)
        point = r  # type: _ScoredPointLike
        text = _extract_text_from_payload(point.payload)
        if not text:
            # Skip empty/unsupported payloads rather than polluting evidence.
            continue
        chunks.append(RetrievedChunk(text=text, score=float(point.score)))

    # 4) Return RetrievalResponse
    return RetrievalResponse(chunks=chunks)
