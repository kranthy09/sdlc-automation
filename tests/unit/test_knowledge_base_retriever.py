"""
Unit tests for KnowledgeBaseRetriever.
"""

from __future__ import annotations

import pytest

from platform.retrieval.knowledge_base import KnowledgeBaseRetriever
from platform.retrieval.vector_store import Point, SearchHit


class MockVectorStore:
    """Mock VectorStore for testing."""

    def __init__(self, docs: list[dict] | None = None):
        self.docs = docs or []
        self.last_query: dict = {}

    def collection_exists(self, name: str) -> bool:
        return True

    def search(
        self,
        collection: str,
        dense_vector: list[float],
        top_k: int,
        payload_filter: dict | None = None,
        sparse: tuple | None = None,
    ) -> list[SearchHit]:
        self.last_query = {
            "collection": collection,
            "top_k": top_k,
            "payload_filter": payload_filter,
        }
        filtered = self.docs
        if payload_filter and "module" in payload_filter:
            module_filter = payload_filter["module"]
            filtered = [d for d in self.docs if d.get("module") == module_filter]

        return [
            SearchHit(
                id=doc["id"],
                score=doc.get("score", 0.5),
                payload={
                    "module": doc["module"],
                    "feature": doc["feature"],
                    "title": doc["title"],
                    "text": doc["text"],
                    "url": doc.get("url"),
                },
            )
            for doc in filtered[:top_k]
        ]


@pytest.fixture
def mock_docs():
    """Sample documents for testing."""
    return [
        {
            "id": "doc-ap-0001",
            "module": "AccountsPayable",
            "feature": "Invoice Matching",
            "title": "Set up invoice matching",
            "text": "Configure three-way matching in AP parameters.",
            "url": "https://learn.microsoft.com/ap-matching",
            "score": 0.95,
        },
        {
            "id": "doc-ap-0002",
            "module": "AccountsPayable",
            "feature": "Payment Proposal",
            "title": "Create payment proposals",
            "text": "Automate invoice selection for payment.",
            "url": "https://learn.microsoft.com/ap-payment",
            "score": 0.87,
        },
        {
            "id": "doc-gl-0001",
            "module": "GeneralLedger",
            "feature": "Financial Dimensions",
            "title": "Financial dimensions overview",
            "text": "Multi-dimensional cost accounting setup.",
            "url": "https://learn.microsoft.com/gl-dims",
            "score": 0.92,
        },
    ]


def test_fetch_all(mock_docs):
    """Test fetching all documents."""
    store = MockVectorStore(mock_docs)
    retriever = KnowledgeBaseRetriever("http://localhost:6333", _store=store)

    docs = retriever.fetch_all("d365_fo")

    assert len(docs) == 3
    assert docs[0]["id"] == "doc-ap-0001"
    assert docs[0]["module"] == "AccountsPayable"


def test_fetch_all_with_module_filter(mock_docs):
    """Test fetching documents filtered by module."""
    store = MockVectorStore(mock_docs)
    retriever = KnowledgeBaseRetriever("http://localhost:6333", _store=store)

    docs = retriever.fetch_all("d365_fo", module_filter="AccountsPayable")

    assert len(docs) == 2
    assert all(d["module"] == "AccountsPayable" for d in docs)


def test_fetch_search(mock_docs):
    """Test semantic search."""
    store = MockVectorStore(mock_docs)
    retriever = KnowledgeBaseRetriever("http://localhost:6333", _store=store)

    query_vec = [0.1] * 384  # Dummy embedding
    docs = retriever.fetch_search("d365_fo", query_vec, top_k=2)

    assert len(docs) == 2
    assert docs[0]["id"] == "doc-ap-0001"
    assert docs[0]["score"] == 0.95


def test_list_modules(mock_docs):
    """Test listing available modules."""
    store = MockVectorStore(mock_docs)
    retriever = KnowledgeBaseRetriever("http://localhost:6333", _store=store)

    modules = retriever.list_modules("d365_fo")

    assert modules == ["AccountsPayable", "GeneralLedger"]


def test_fetch_all_missing_collection():
    """Test behavior when collection is missing."""
    store = MockVectorStore([])
    store.collection_exists = lambda name: False
    retriever = KnowledgeBaseRetriever("http://localhost:6333", _store=store)

    docs = retriever.fetch_all("d365_fo")

    assert docs == []


def test_payload_structure(mock_docs):
    """Test that payload fields are correctly extracted."""
    store = MockVectorStore(mock_docs)
    retriever = KnowledgeBaseRetriever("http://localhost:6333", _store=store)

    docs = retriever.fetch_all("d365_fo")

    for doc in docs:
        assert "id" in doc
        assert "module" in doc
        assert "feature" in doc
        assert "title" in doc
        assert "text" in doc
        assert "url" in doc
        assert "score" in doc
