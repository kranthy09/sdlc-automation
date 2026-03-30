"""
Unit tests for knowledge base API routes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.routes.knowledge_base import router, _to_document_item
from api.models import DocumentItem


@pytest.fixture
def client():
    """FastAPI test client for knowledge base routes."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


@pytest.fixture
def mock_docs():
    """Sample documents."""
    return [
        {
            "id": "doc-ap-0001",
            "module": "AccountsPayable",
            "feature": "Invoice Matching",
            "title": "Set up invoice matching",
            "text": "Configure three-way matching.",
            "url": "https://learn.microsoft.com/ap-matching",
            "score": None,
        },
        {
            "id": "doc-ap-0002",
            "module": "AccountsPayable",
            "feature": "Payment Proposal",
            "title": "Create payment proposals",
            "text": "Automate invoice selection.",
            "url": "https://learn.microsoft.com/ap-payment",
            "score": None,
        },
        {
            "id": "doc-gl-0001",
            "module": "GeneralLedger",
            "feature": "Financial Dimensions",
            "title": "Financial dimensions",
            "text": "Multi-dimensional cost accounting.",
            "url": "https://learn.microsoft.com/gl-dims",
            "score": None,
        },
    ]


def test_list_knowledge_base_docs(client, mock_docs):
    """Test GET /api/v1/{product}/knowledge-base/docs."""
    with patch("api.routes.knowledge_base.KnowledgeBaseRetriever") as MockRetriever:
        mock_retriever = MagicMock()
        mock_retriever.fetch_all.return_value = mock_docs
        MockRetriever.return_value = mock_retriever

        response = client.get("/api/v1/d365_fo/knowledge-base/docs")

        assert response.status_code == 200
        data = response.json()

        assert data["product"] == "d365_fo"
        assert data["total_count"] == 3
        assert len(data["documents"]) == 3

        # Check module counts
        assert data["module_counts"]["AccountsPayable"] == 2
        assert data["module_counts"]["GeneralLedger"] == 1


def test_list_knowledge_base_docs_with_module_filter(client, mock_docs):
    """Test GET /api/v1/{product}/knowledge-base/docs?module=AccountsPayable."""
    filtered_docs = [doc for doc in mock_docs if doc["module"] == "AccountsPayable"]

    with patch("api.routes.knowledge_base.KnowledgeBaseRetriever") as MockRetriever:
        mock_retriever = MagicMock()
        mock_retriever.fetch_all.return_value = filtered_docs
        MockRetriever.return_value = mock_retriever

        response = client.get(
            "/api/v1/d365_fo/knowledge-base/docs",
            params={"module": "AccountsPayable"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total_count"] == 2
        assert len(data["documents"]) == 2
        assert all(doc["module"] == "AccountsPayable" for doc in data["documents"])


def test_list_modules(client):
    """Test GET /api/v1/{product}/knowledge-base/modules."""
    with patch("api.routes.knowledge_base.KnowledgeBaseRetriever") as MockRetriever:
        mock_retriever = MagicMock()
        mock_retriever.list_modules.return_value = [
            "AccountsPayable",
            "GeneralLedger",
            "Procurement",
        ]
        MockRetriever.return_value = mock_retriever

        response = client.get("/api/v1/d365_fo/knowledge-base/modules")

        assert response.status_code == 200
        data = response.json()

        assert data["product"] == "d365_fo"
        assert data["count"] == 3
        assert "AccountsPayable" in data["modules"]
        assert "GeneralLedger" in data["modules"]
        assert "Procurement" in data["modules"]


def test_list_knowledge_base_docs_error(client):
    """Test error handling when knowledge base is unavailable."""
    with patch("api.routes.knowledge_base.KnowledgeBaseRetriever") as MockRetriever:
        mock_retriever = MagicMock()
        mock_retriever.fetch_all.side_effect = RuntimeError("Qdrant connection failed")
        MockRetriever.return_value = mock_retriever

        response = client.get("/api/v1/d365_fo/knowledge-base/docs")

        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()


def test_to_document_item():
    """Test conversion of internal doc dict to DocumentItem."""
    doc = {
        "id": "doc-ap-0001",
        "module": "AccountsPayable",
        "feature": "Invoice Matching",
        "title": "Set up invoice matching",
        "text": "Configure three-way matching.",
        "url": "https://learn.microsoft.com/ap-matching",
        "score": 0.95,
    }

    item = _to_document_item(doc)

    assert isinstance(item, DocumentItem)
    assert item.id == "doc-ap-0001"
    assert item.module == "AccountsPayable"
    assert item.score == 0.95


def test_document_item_response_schema(mock_docs):
    """Test DocumentItem schema matches API response."""
    from api.models import KnowledgeBaseListResponse

    items = [_to_document_item(doc) for doc in mock_docs]
    response = KnowledgeBaseListResponse(
        product="d365_fo",
        documents=items,
        total_count=len(items),
        module_counts={"AccountsPayable": 2, "GeneralLedger": 1},
    )

    data = response.model_dump()

    assert data["product"] == "d365_fo"
    assert data["total_count"] == 3
    assert len(data["documents"]) == 3
    assert data["module_counts"]["AccountsPayable"] == 2
