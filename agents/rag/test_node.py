from __future__ import annotations

from typing import Any

import pytest

from agents.rag.node import rag_retrieval_node
from platforms.schemas.retrieval import RetrievalQuery


def test_rag_node_returns_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock embedding generation (avoid sentence-transformers dependency)
    def fake_embed(text: str) -> list[float]:
        assert text == "hello world"
        return [0.1, 0.2, 0.3]

    # Mock retriever (avoid Qdrant dependency)
    class FakePoint:
        def __init__(self, score: float, payload: dict[str, Any]) -> None:
            self.score = score
            self.payload = payload

    def fake_search(vector: list[float], top_k: int) -> list[FakePoint]:
        assert vector == [0.1, 0.2, 0.3]
        assert top_k == 2
        return [
            FakePoint(0.9, {"text": "chunk A"}),
            FakePoint(0.8, {"text": "chunk B"}),
        ]

    # Patch the functions used inside agents.rag.node
    import agents.rag.node as node

    monkeypatch.setattr(node, "embed", fake_embed)
    monkeypatch.setattr(node, "search", fake_search)

    # Create query and call the node
    q = RetrievalQuery(query="hello world", top_k=2)
    resp = rag_retrieval_node(q)

    # Assert response shape/content
    assert len(resp.chunks) == 2
    assert resp.chunks[0].text == "chunk A"
    assert resp.chunks[0].score == 0.9
    assert resp.chunks[1].text == "chunk B"
    assert resp.chunks[1].score == 0.8
