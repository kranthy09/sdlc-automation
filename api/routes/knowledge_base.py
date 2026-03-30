"""
Knowledge base routes — read-only API for browsing documents.

Rule: zero business logic. Routes dispatch to KnowledgeBaseRetriever
and format responses using api/models.py types.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.models import DocumentItem, KnowledgeBaseListResponse
from platform.retrieval.knowledge_base import KnowledgeBaseRetriever
from platform.config.settings import get_settings

log = structlog.get_logger(__name__)

router = APIRouter(tags=["knowledge-base"])


def _to_document_item(doc: dict[str, Any]) -> DocumentItem:
    """Convert internal doc dict to API response type."""
    return DocumentItem(
        id=doc.get("id", ""),
        module=doc.get("module", ""),
        feature=doc.get("feature", ""),
        title=doc.get("title", ""),
        text=doc.get("text", ""),
        url=doc.get("url"),
        score=doc.get("score"),
    )


@router.get(
    "/{product_id}/knowledge-base/docs",
    response_model=KnowledgeBaseListResponse,
)
def list_knowledge_base_docs(
    product_id: str,
    module: str | None = Query(None, description="Filter by module name"),
) -> KnowledgeBaseListResponse:
    """Fetch all documents in the knowledge base for a product.

    Query Parameters:
        module (optional): Filter results by exact module name match.

    Returns:
        List of documents with module counts.

    Raises:
        HTTPException: If the knowledge base collection is missing or inaccessible.
    """
    settings = get_settings()
    retriever = KnowledgeBaseRetriever(settings.qdrant_url)

    try:
        docs = retriever.fetch_all(product_id, module_filter=module)

        # Convert to DocumentItem response types
        items = [_to_document_item(doc) for doc in docs]

        # Calculate module counts
        module_counts: dict[str, int] = {}
        for doc in docs:
            mod = doc.get("module", "")
            if mod:
                module_counts[mod] = module_counts.get(mod, 0) + 1

        log.info(
            "knowledge_base_docs_list",
            product=product_id,
            count=len(items),
            module_filter=module,
        )

        return KnowledgeBaseListResponse(
            product=product_id,
            documents=items,
            total_count=len(items),
            module_counts=module_counts,
        )

    except Exception as exc:
        log.error(
            "knowledge_base_docs_error",
            product=product_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail=f"Knowledge base unavailable: {str(exc)}",
        ) from exc


@router.get(
    "/{product_id}/knowledge-base/modules",
    response_model=dict[str, Any],
)
def list_modules(product_id: str) -> dict[str, Any]:
    """Fetch list of available modules in the knowledge base.

    Returns:
        Object with 'modules' list and 'product' identifier.

    Raises:
        HTTPException: If the knowledge base collection is missing or inaccessible.
    """
    settings = get_settings()
    retriever = KnowledgeBaseRetriever(settings.qdrant_url)

    try:
        modules = retriever.list_modules(product_id)

        log.info(
            "knowledge_base_modules_list",
            product=product_id,
            count=len(modules),
        )

        return {
            "product": product_id,
            "modules": modules,
            "count": len(modules),
        }

    except Exception as exc:
        log.error(
            "knowledge_base_modules_error",
            product=product_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail=f"Knowledge base unavailable: {str(exc)}",
        ) from exc
