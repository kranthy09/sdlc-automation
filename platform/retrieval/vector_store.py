"""
Vector store — wraps Qdrant for dense and hybrid (dense + sparse) search.

Supports two collection types driven by CollectionConfig:
  - Dense-only:  VectorParams(size=N, distance=COSINE)
  - Hybrid:      named "dense" + "sparse" vectors with RRF fusion

String point IDs (e.g. "cap-ap-0001") are hashed to deterministic UUIDs
internally — Qdrant requires UUID or int IDs. The original ID is stored in
the payload under "_id" and restored on every SearchHit so callers see their
original identifiers transparently.

Usage:
    from platform.retrieval.vector_store import VectorStore, CollectionConfig, Point

    store = VectorStore(settings.qdrant_url)

    # One-time collection setup (idempotent):
    store.ensure_collection("d365_fo_capabilities", CollectionConfig(sparse=True))

    # Upsert capability points:
    store.upsert("d365_fo_capabilities", [
        Point(
            id="cap-ap-0001",
            dense_vector=[...],           # 384-dim bge-small embedding
            payload={"module": "AccountsPayable", "feature": "Three-way matching"},
            sparse_indices=[0, 5, 12],    # BM25 term indices
            sparse_values=[1.0, 0.8, 0.6],
        )
    ])

    # Search (hybrid):
    hits = store.search(
        "d365_fo_capabilities",
        query_vec,
        top_k=20,
        payload_filter={"module": "AccountsPayable"},
        sparse=([0, 5, 12], [1.0, 0.8, 0.6]),
    )
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from platform.observability.logger import get_logger

log = get_logger(__name__)

# Namespace for deterministic UUID5 hashing of string IDs
_UUID_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

_DISTANCE_MAP = {
    "cosine": "COSINE",
    "dot": "DOT",
    "euclidean": "EUCLID",
}


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class VectorStoreError(Exception):
    """Raised when a Qdrant operation fails."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)


# ---------------------------------------------------------------------------
# Public data types (Qdrant-agnostic — modules never import qdrant_client)
# ---------------------------------------------------------------------------


@dataclass
class CollectionConfig:
    """Configuration for a Qdrant collection.

    Args:
        size:     Embedding dimension. Default 384 (bge-small-en-v1.5).
        distance: Similarity metric — "cosine" | "dot" | "euclidean".
        sparse:   True → hybrid collection with named "dense" + "sparse" vectors.
                  False → dense-only collection (unnamed vector).
    """

    size: int = 384
    distance: str = "cosine"
    sparse: bool = False


@dataclass
class Point:
    """A single point to upsert into a collection.

    Args:
        id:             Caller-supplied ID (str or int).
                        Strings are converted to deterministic UUIDs internally.
        dense_vector:   Dense embedding of length == CollectionConfig.size.
        payload:        Arbitrary metadata stored alongside the vector.
        sparse_indices: Non-zero BM25 term indices (hybrid collections only).
        sparse_values:  Corresponding BM25 weights (parallel to sparse_indices).
    """

    id: str | int
    dense_vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)


@dataclass
class SearchHit:
    """A single result returned by a vector search."""

    id: str | int  # caller's original ID, restored from payload "_id"
    score: float
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------


class VectorStore:
    """Qdrant-backed vector store.

    Args:
        url:      Qdrant server URL, e.g. "http://localhost:6333".
        _client:  Pre-built QdrantClient — for testing only; bypasses lazy init.
    """

    def __init__(
        self,
        url: str,
        *,
        _client: Any = None,
    ) -> None:
        self._url = url
        self._client: Any = _client

    # ------------------------------------------------------------------
    # Client (lazy)
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            import qdrant_client  # noqa: PLC0415

            log.info("vector_store_connect", url=self._url)
            self._client = qdrant_client.QdrantClient(url=self._url)
        return self._client

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def collection_exists(self, name: str) -> bool:
        """Return True if the named collection exists."""
        try:
            return bool(self._get_client().collection_exists(name))
        except Exception as exc:
            raise VectorStoreError(
                f"collection_exists({name!r}) failed: {exc}", cause=exc) from exc

    def collection_point_count(self, name: str) -> int:
        """Return the number of points in a collection."""
        try:
            info = self._get_client().get_collection(name)
            return info.points_count or 0
        except Exception as exc:
            raise VectorStoreError(
                f"collection_point_count({name!r}) failed: {exc}",
                cause=exc,
            ) from exc

    def ensure_collection(self, name: str, config: CollectionConfig) -> None:
        """Create the collection if it does not already exist (idempotent)."""
        if self.collection_exists(name):
            log.debug("vector_store_collection_exists_skip", collection=name)
            return
        self._create_collection(name, config)

    def recreate_collection(self, name: str, config: CollectionConfig) -> None:
        """Drop then recreate the collection — full data wipe (used by seed scripts)."""
        if self.collection_exists(name):
            self.drop_collection(name)
        self._create_collection(name, config)

    def drop_collection(self, name: str) -> None:
        """Delete a collection and all its data permanently."""
        try:
            self._get_client().delete_collection(name)
            log.info("vector_store_drop_collection", collection=name)
        except Exception as exc:
            raise VectorStoreError(
                f"drop_collection({name!r}) failed: {exc}", cause=exc) from exc

    def _create_collection(self, name: str, config: CollectionConfig) -> None:
        from qdrant_client.models import (  # noqa: PLC0415
            Distance,
            SparseIndexParams,
            SparseVectorParams,
            VectorParams,
        )

        distance = Distance[_DISTANCE_MAP[config.distance]]
        try:
            if config.sparse:
                self._get_client().create_collection(
                    collection_name=name,
                    vectors_config={"dense": VectorParams(
                        size=config.size, distance=distance)},
                    sparse_vectors_config={
                        "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))
                    },
                )
            else:
                self._get_client().create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=config.size, distance=distance),
                )
            log.info(
                "vector_store_create_collection",
                collection=name,
                sparse=config.sparse,
            )
        except Exception as exc:
            raise VectorStoreError(
                f"create_collection({name!r}) failed: {exc}", cause=exc) from exc

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(self, collection: str, points: list[Point]) -> None:
        """Insert or update points in the collection.

        String IDs are hashed to deterministic UUIDs; the original ID is
        preserved in payload["_id"] for transparent round-trip retrieval.

        Raises:
            VectorStoreError: If the upsert fails.
        """
        from qdrant_client.models import (
            PointStruct,
            SparseVector,
        )  # noqa: PLC0415

        qdrant_points = []
        for p in points:
            payload = {**p.payload, "_id": p.id}
            if p.sparse_indices:
                vector: Any = {
                    "dense": p.dense_vector,
                    "sparse": SparseVector(indices=p.sparse_indices, values=p.sparse_values),
                }
            else:
                vector = p.dense_vector
            qdrant_points.append(
                PointStruct(id=_to_qdrant_id(p.id),
                            vector=vector, payload=payload)
            )
        try:
            self._get_client().upsert(collection_name=collection, points=qdrant_points)
            log.debug("vector_store_upsert",
                      collection=collection, n=len(points))
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(
                f"upsert({collection!r}) failed: {exc}", cause=exc) from exc

    def delete_points(self, collection: str, ids: list[str | int]) -> None:
        """Remove specific points by their original caller IDs.

        Raises:
            VectorStoreError: If the delete fails.
        """
        from qdrant_client.models import PointIdsList  # noqa: PLC0415

        qdrant_ids = [_to_qdrant_id(i) for i in ids]
        try:
            self._get_client().delete(
                collection_name=collection,
                points_selector=PointIdsList(points=qdrant_ids),
            )
            log.debug("vector_store_delete_points",
                      collection=collection, n=len(ids))
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(
                f"delete_points({collection!r}) failed: {exc}", cause=exc
            ) from exc

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search(
        self,
        collection: str,
        dense_vector: list[float],
        top_k: int,
        *,
        payload_filter: dict[str, str | int | float | bool] | None = None,
        sparse: tuple[list[int], list[float]] | None = None,
    ) -> list[SearchHit]:
        """Search for nearest vectors.

        Args:
            collection:     Target collection name.
            dense_vector:   Query dense embedding.
            top_k:          Maximum results to return.
            payload_filter: AND-combined exact-match filters on payload fields,
                            e.g. {"module": "AccountsPayable"}.
            sparse:         (indices, values) for hybrid RRF fusion search.
                            Omit or pass None for dense-only search.

        Returns:
            List of SearchHit ordered by descending relevance score.

        Raises:
            VectorStoreError: If the search fails.
        """
        try:
            qdrant_filter = _build_filter(payload_filter)
            response = self._run_query(
                collection, dense_vector, top_k, qdrant_filter, sparse)
            hits = [_to_hit(p) for p in response.points]
            log.debug(
                "vector_store_search",
                collection=collection,
                top_k=top_k,
                hits=len(hits),
            )
            return hits
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(
                f"search({collection!r}) failed: {exc}", cause=exc) from exc

    def _run_query(
        self,
        collection: str,
        dense_vector: list[float],
        top_k: int,
        qdrant_filter: Any,
        sparse: tuple[list[int], list[float]] | None,
    ) -> Any:
        if sparse is not None:
            return self._hybrid_query(collection, dense_vector, sparse, top_k, qdrant_filter)
        return self._dense_query(collection, dense_vector, top_k, qdrant_filter)

    def _dense_query(
        self,
        collection: str,
        dense_vector: list[float],
        top_k: int,
        qdrant_filter: Any,
    ) -> Any:
        return self._get_client().query_points(
            collection_name=collection,
            query=dense_vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )

    def _hybrid_query(
        self,
        collection: str,
        dense_vector: list[float],
        sparse: tuple[list[int], list[float]],
        top_k: int,
        qdrant_filter: Any,
    ) -> Any:
        from qdrant_client.models import (  # noqa: PLC0415
            Fusion,
            FusionQuery,
            Prefetch,
            SparseVector,
        )

        indices, values = sparse
        return self._get_client().query_points(
            collection_name=collection,
            prefetch=[
                Prefetch(query=dense_vector, using="dense", limit=top_k * 2),
                Prefetch(
                    query=SparseVector(indices=indices, values=values),
                    using="sparse",
                    limit=top_k * 2,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _to_qdrant_id(raw_id: str | int) -> str | int:
    """Map a caller ID to a Qdrant-compatible point ID (UUID or int)."""
    if isinstance(raw_id, int):
        return raw_id
    return str(uuid.uuid5(_UUID_NS, raw_id))


def _build_filter(raw: dict[str, str | int | float | bool] | None) -> Any:
    """Convert a flat payload dict to a Qdrant Filter (AND of MatchValue conditions)."""
    if not raw:
        return None
    from qdrant_client.models import (
        FieldCondition,
        Filter,
        MatchValue,
    )  # noqa: PLC0415

    return Filter(must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in raw.items()])


def _to_hit(scored_point: Any) -> SearchHit:
    """Convert a Qdrant ScoredPoint to a SearchHit, restoring the original ID."""
    payload = dict(scored_point.payload or {})
    original_id: str | int = payload.pop("_id", str(scored_point.id))
    return SearchHit(id=original_id, score=scored_point.score, payload=payload)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def get_store(url: str) -> VectorStore:
    """Return a VectorStore connected to *url*."""
    return VectorStore(url)
