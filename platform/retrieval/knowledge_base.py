"""
Knowledge base retriever — fetch documents from Qdrant.

Provides a read-only interface to query document collections seeded by
infra/scripts/seed_knowledge_base.py. Documents are indexed in Qdrant
under collections named `{product_id}_docs`.

Usage:
    from platform.retrieval.knowledge_base import KnowledgeBaseRetriever

    retriever = KnowledgeBaseRetriever(
        qdrant_url="http://localhost:6333"
    )

    # Fetch all docs for a product
    docs = retriever.fetch_all(product_id="d365_fo")

    # Fetch with module filter
    ap_docs = retriever.fetch_all(
        product_id="d365_fo",
        module_filter="AccountsPayable"
    )

    # Fetch with text search (via BM25 similarity)
    search_docs = retriever.fetch_search(
        product_id="d365_fo",
        query="invoice payment",
        top_k=10
    )
"""

from __future__ import annotations

from typing import Any

from platform.observability.logger import get_logger
from platform.retrieval.vector_store import VectorStore, VectorStoreError

log = get_logger(__name__)


class KnowledgeBaseRetriever:
    """Query documents from Qdrant knowledge base collections.

    Args:
        qdrant_url: Qdrant server URL, e.g. "http://localhost:6333".
        _store:     Pre-built VectorStore — for testing only.
    """

    def __init__(
        self,
        qdrant_url: str,
        *,
        _store: VectorStore | None = None,
    ) -> None:
        self._store = _store or VectorStore(qdrant_url)

    def _collection_name(self, product_id: str) -> str:
        """Derive collection name from product ID."""
        return f"{product_id}_docs"

    def fetch_all(
        self,
        product_id: str,
        *,
        module_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all documents for a product, optionally filtered by module.

        Args:
            product_id:     Product identifier (e.g., "d365_fo").
            module_filter:  Optional module name to filter (exact match).

        Returns:
            List of document dicts with keys: id, module, feature, title, text, url, score.
            Score is None for non-search queries.

        Raises:
            VectorStoreError: If the collection is missing or query fails.
        """
        collection = self._collection_name(product_id)

        try:
            if not self._store.collection_exists(collection):
                log.warning(
                    "knowledge_base_collection_missing",
                    collection=collection,
                    product=product_id,
                )
                return []

            # Fetch all points without vector search (use large top_k)
            # Qdrant scroll is not exposed by VectorStore, so we use a search with zero vector
            # This is a workaround; in production, extend VectorStore to support scroll.
            dummy_vector = [0.0] * 384
            payload_filter = None
            if module_filter:
                payload_filter = {"module": module_filter}

            hits = self._store.search(
                collection,
                dummy_vector,
                top_k=10000,  # Practical limit for API response
                payload_filter=payload_filter,
            )

            docs = [
                {
                    "id": hit.id,
                    "module": hit.payload.get("module", ""),
                    "feature": hit.payload.get("feature", ""),
                    "title": hit.payload.get("title", ""),
                    "text": hit.payload.get("text", ""),
                    "url": hit.payload.get("url"),
                    "score": None,
                }
                for hit in hits
            ]

            log.debug(
                "knowledge_base_fetch_all",
                collection=collection,
                count=len(docs),
                module_filter=module_filter,
            )
            return docs

        except VectorStoreError as exc:
            log.error(
                "knowledge_base_fetch_error",
                collection=collection,
                product=product_id,
                error=str(exc),
            )
            raise

    def fetch_search(
        self,
        product_id: str,
        query_vector: list[float],
        *,
        top_k: int = 20,
        module_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search documents by semantic similarity.

        Args:
            product_id:     Product identifier (e.g., "d365_fo").
            query_vector:   Dense embedding of the search query (length 384).
            top_k:          Maximum results to return.
            module_filter:  Optional module name to filter (exact match).

        Returns:
            List of document dicts with relevance scores (descending order).

        Raises:
            VectorStoreError: If the collection is missing or query fails.
        """
        collection = self._collection_name(product_id)

        try:
            if not self._store.collection_exists(collection):
                log.warning(
                    "knowledge_base_collection_missing",
                    collection=collection,
                    product=product_id,
                )
                return []

            payload_filter = None
            if module_filter:
                payload_filter = {"module": module_filter}

            hits = self._store.search(
                collection,
                query_vector,
                top_k=top_k,
                payload_filter=payload_filter,
            )

            docs = [
                {
                    "id": hit.id,
                    "module": hit.payload.get("module", ""),
                    "feature": hit.payload.get("feature", ""),
                    "title": hit.payload.get("title", ""),
                    "text": hit.payload.get("text", ""),
                    "url": hit.payload.get("url"),
                    "score": hit.score,
                }
                for hit in hits
            ]

            log.debug(
                "knowledge_base_fetch_search",
                collection=collection,
                product=product_id,
                top_k=top_k,
                results=len(docs),
                module_filter=module_filter,
            )
            return docs

        except VectorStoreError as exc:
            log.error(
                "knowledge_base_search_error",
                collection=collection,
                product=product_id,
                error=str(exc),
            )
            raise

    def list_modules(self, product_id: str) -> list[str]:
        """Fetch list of unique modules in the knowledge base.

        Args:
            product_id: Product identifier (e.g., "d365_fo").

        Returns:
            Sorted list of module names.

        Raises:
            VectorStoreError: If the collection is missing or query fails.
        """
        docs = self.fetch_all(product_id)
        modules = sorted(set(doc.get("module", "") for doc in docs if doc.get("module")))
        log.debug(
            "knowledge_base_list_modules",
            product=product_id,
            module_count=len(modules),
        )
        return modules
