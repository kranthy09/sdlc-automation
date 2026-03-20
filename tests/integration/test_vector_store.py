"""
Integration — platform/retrieval/vector_store.py

Uses QdrantClient(':memory:') by default so tests run without Docker.
Set QDRANT_URL=http://localhost:6333 to run against a real Qdrant server.

Tests cover:
  - ensure_collection is idempotent (no error on repeat call)
  - dense search returns the geometrically nearest point
  - payload filter narrows results to matching points only
  - hybrid (dense + sparse) search returns results via RRF fusion
  - delete_points removes specific points
  - recreate_collection wipes all data
  - Prometheus ok metric recorded after a successful search
"""

from __future__ import annotations

import os
import uuid

import pytest
from prometheus_client import CollectorRegistry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIM = 8  # small dimension for test speed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit(index: int) -> list[float]:
    """Return a unit vector with 1.0 at *index*, 0.0 elsewhere."""
    v = [0.0] * DIM
    v[index] = 1.0
    return v


def _sample(registry: CollectorRegistry, labels: dict[str, str]) -> float:
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == "platform_external_calls_total" and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qdrant_client():
    """
    Return a Qdrant client.

    Prefers a real server at QDRANT_URL if set and reachable.
    Falls back to QdrantClient(':memory:') for CI / no-Docker environments.
    """
    from qdrant_client import QdrantClient

    url = os.getenv("QDRANT_URL")
    if url:
        import httpx

        try:
            httpx.get(f"{url}/healthz", timeout=2.0)
        except Exception:
            pytest.skip(f"QDRANT_URL={url!r} not reachable")
        return QdrantClient(url=url)

    # In-memory — same qdrant library, no server required
    return QdrantClient(":memory:")


@pytest.fixture
def store(qdrant_client):
    from platform.retrieval.vector_store import VectorStore

    return VectorStore("http://unused", registry=CollectorRegistry(), _client=qdrant_client)


@pytest.fixture
def dense_col(store):
    """Yield a unique dense collection name; clean up after the test."""
    from platform.retrieval.vector_store import CollectionConfig

    name = f"test_dense_{uuid.uuid4().hex[:8]}"
    store.ensure_collection(name, CollectionConfig(size=DIM, sparse=False))
    yield name
    store.drop_collection(name)


@pytest.fixture
def hybrid_col(store):
    """Yield a unique hybrid collection name; clean up after the test."""
    from platform.retrieval.vector_store import CollectionConfig

    name = f"test_hybrid_{uuid.uuid4().hex[:8]}"
    store.ensure_collection(name, CollectionConfig(size=DIM, sparse=True))
    yield name
    store.drop_collection(name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_ensure_collection_is_idempotent(store, dense_col):
    """Second ensure_collection call on an existing collection must not raise."""
    from platform.retrieval.vector_store import CollectionConfig

    store.ensure_collection(dense_col, CollectionConfig(size=DIM, sparse=False))
    assert store.collection_exists(dense_col)


@pytest.mark.integration
def test_dense_search_returns_nearest_point(store, dense_col):
    """Search with a query equal to cap-001's vector → cap-001 is top hit with score ≈ 1.0."""
    from platform.retrieval.vector_store import Point

    store.upsert(
        dense_col,
        [
            Point(id="cap-001", dense_vector=_unit(0), payload={"module": "AP"}),
            Point(id="cap-002", dense_vector=_unit(1), payload={"module": "GL"}),
            Point(id="cap-003", dense_vector=_unit(2), payload={"module": "AR"}),
        ],
    )

    hits = store.search(dense_col, _unit(0), top_k=3)

    assert len(hits) >= 1
    assert hits[0].id == "cap-001"
    assert hits[0].score == pytest.approx(1.0, abs=1e-4)
    assert hits[0].payload.get("module") == "AP"


@pytest.mark.integration
def test_payload_filter_narrows_results(store, dense_col):
    """payload_filter={"module": "GL"} must exclude AP points entirely."""
    from platform.retrieval.vector_store import Point

    store.upsert(
        dense_col,
        [
            Point(id="ap-1", dense_vector=_unit(0), payload={"module": "AP"}),
            Point(id="gl-1", dense_vector=_unit(1), payload={"module": "GL"}),
        ],
    )

    hits = store.search(dense_col, _unit(0), top_k=10, payload_filter={"module": "GL"})

    assert len(hits) == 1
    assert hits[0].id == "gl-1"
    assert hits[0].payload.get("module") == "GL"


@pytest.mark.integration
def test_hybrid_search_returns_fused_results(store, hybrid_col):
    """Hybrid RRF search returns the point matching both dense and sparse signals."""
    from platform.retrieval.vector_store import Point

    store.upsert(
        hybrid_col,
        [
            Point(
                id="h-001",
                dense_vector=_unit(0),
                payload={"module": "AP"},
                sparse_indices=[0, 1],
                sparse_values=[1.0, 0.5],
            ),
            Point(
                id="h-002",
                dense_vector=_unit(1),
                payload={"module": "GL"},
                sparse_indices=[2, 3],
                sparse_values=[0.8, 0.3],
            ),
        ],
    )

    hits = store.search(
        hybrid_col,
        _unit(0),
        top_k=5,
        sparse=([0, 1], [1.0, 0.5]),
    )

    assert len(hits) >= 1
    assert hits[0].id == "h-001"


@pytest.mark.integration
def test_delete_points_removes_them(store, dense_col):
    """delete_points removes the specified points; subsequent search does not return them."""
    from platform.retrieval.vector_store import Point

    store.upsert(dense_col, [Point(id="del-1", dense_vector=_unit(3), payload={})])
    before = store.search(dense_col, _unit(3), top_k=5)
    assert any(h.id == "del-1" for h in before)

    store.delete_points(dense_col, ["del-1"])
    after = store.search(dense_col, _unit(3), top_k=5)
    assert not any(h.id == "del-1" for h in after)


@pytest.mark.integration
def test_recreate_collection_wipes_data(qdrant_client):
    """recreate_collection drops all points; search returns empty results after rebuild."""
    from platform.retrieval.vector_store import CollectionConfig, Point, VectorStore

    store = VectorStore("http://unused", registry=CollectorRegistry(), _client=qdrant_client)
    name = f"test_recreate_{uuid.uuid4().hex[:8]}"
    cfg = CollectionConfig(size=DIM, sparse=False)

    try:
        store.ensure_collection(name, cfg)
        store.upsert(name, [Point(id="old-1", dense_vector=_unit(0), payload={})])

        before = store.search(name, _unit(0), top_k=5)
        assert len(before) == 1

        store.recreate_collection(name, cfg)
        after = store.search(name, _unit(0), top_k=5)
        assert len(after) == 0
    finally:
        store.drop_collection(name)


@pytest.mark.integration
def test_search_records_ok_prometheus_metric(qdrant_client):
    """platform_external_calls_total{service=qdrant, status=ok} increments on success."""
    from platform.retrieval.vector_store import CollectionConfig, Point, VectorStore

    registry = CollectorRegistry()
    store = VectorStore("http://unused", registry=registry, _client=qdrant_client)
    name = f"test_metrics_{uuid.uuid4().hex[:8]}"

    try:
        store.ensure_collection(name, CollectionConfig(size=DIM))
        store.upsert(name, [Point(id="m-1", dense_vector=_unit(0), payload={})])
        store.search(name, _unit(0), top_k=5)

        value = _sample(registry, {"service": "qdrant", "operation": "search", "status": "ok"})
        assert value == 1.0
    finally:
        store.drop_collection(name)
