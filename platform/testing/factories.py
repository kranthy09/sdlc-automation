"""
Test factories — centralised mock builders for Layer 3+ module tests.

Every DYNAFIT node test imports from here instead of instantiating real
infrastructure.  This is the ONLY place where mock infrastructure is
constructed, keeping mocks consistent with the platform contracts they
replace.

Factory categories:

  Infrastructure mocks
    make_llm_client     — mock LLMClient returning canned Pydantic objects
    make_embedder       — mock Embedder returning deterministic zero vectors
    make_vector_store   — mock VectorStore returning pre-configured SearchHits
    make_postgres_store — async mock PostgresStore, optionally seeded with priors
    make_redis_pub_sub  — async mock RedisPubSub that yields events then stops

  Schema factories
    make_product_config, make_raw_upload, make_requirement_atom,
    make_validated_atom, make_ranked_capability, make_prior_fitment,
    make_classification_result, make_assembled_context,
    make_match_result, make_search_hit

All schema factories accept **overrides so tests only specify the fields
that matter for the assertion under test.

Usage (inside a DYNAFIT node test)::

    from platform.testing.factories import (
        make_llm_client,
        make_validated_atom,
        make_classification_result,
        make_product_config,
    )
    from platform.schemas.fitment import FitLabel

    llm   = make_llm_client(make_classification_result(classification=FitLabel.FIT))
    atom  = make_validated_atom(module="AccountsPayable")
    cfg   = make_product_config()
    result = classify_node.run(atom, llm=llm, config=cfg)
    assert result.classification == FitLabel.FIT
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import numpy as np
from prometheus_client import CollectorRegistry
from pydantic import BaseModel

from platform.llm.client import LLMClient
from platform.retrieval.embedder import Embedder
from platform.retrieval.vector_store import SearchHit, VectorStore
from platform.schemas.fitment import (
    ClassificationResult,
    FitLabel,
    MatchResult,
    RouteLabel,
)
from platform.schemas.product import ProductConfig
from platform.schemas.requirement import RawUpload, RequirementAtom, ValidatedAtom
from platform.schemas.retrieval import (
    AssembledContext,
    PriorFitment,
    RankedCapability,
)
from platform.storage.postgres import PostgresStore
from platform.storage.redis_pub import RedisPubSub

__all__ = [
    # Infrastructure mocks
    "make_llm_client",
    "make_embedder",
    "make_vector_store",
    "make_postgres_store",
    "make_redis_pub_sub",
    # Schema factories
    "make_product_config",
    "make_raw_upload",
    "make_requirement_atom",
    "make_validated_atom",
    "make_ranked_capability",
    "make_prior_fitment",
    "make_classification_result",
    "make_assembled_context",
    "make_match_result",
    "make_search_hit",
]


# ---------------------------------------------------------------------------
# Infrastructure mocks
# ---------------------------------------------------------------------------


def make_llm_client(*responses: BaseModel) -> LLMClient:
    """Return a mock LLMClient whose ``complete()`` returns *responses* in order.

    Each call to ``complete()`` consumes the next response.  Pass multiple
    responses for nodes that make more than one LLM call per requirement
    (e.g. DEEP_REASON routing calls three times and takes a majority vote).

    Args:
        *responses: Pydantic model instances to return from ``complete()``,
                    one per call.  If none are given, ``complete`` returns
                    a plain ``MagicMock``.

    Example::

        llm = make_llm_client(
            make_classification_result(classification=FitLabel.FIT),
            make_classification_result(classification=FitLabel.FIT),
            make_classification_result(classification=FitLabel.PARTIAL_FIT),
        )
        # Three calls → majority FIT
    """
    client: MagicMock = MagicMock(spec=LLMClient)
    if responses:
        client.complete.side_effect = list(responses)
    return cast(LLMClient, client)


def make_embedder(*, dim: int = 384) -> Embedder:
    """Return a mock Embedder that returns zero vectors of *dim* dimensions.

    The underlying mock handles both single-text ``embed()`` and batch
    ``embed_batch()`` calls: a str input yields a 1-D array; a list input
    yields a 2-D array (one row per text).

    Args:
        dim: Vector dimension.  Default 384 matches BAAI/bge-small-en-v1.5.
    """
    mock_model: MagicMock = MagicMock()

    def _encode(texts: str | list[str]) -> Any:
        if isinstance(texts, list):
            return np.zeros((len(texts), dim), dtype=np.float32)
        return np.zeros(dim, dtype=np.float32)

    mock_model.encode.side_effect = _encode
    return Embedder("test-model", _model=mock_model, registry=CollectorRegistry())


def make_vector_store(hits: list[SearchHit] | None = None) -> VectorStore:
    """Return a mock VectorStore whose ``search()`` returns *hits*.

    Collection management (ensure, recreate, drop) and write operations
    (upsert, delete_points) are silent no-ops.  ``collection_exists``
    returns ``True`` so idempotent collection setup skips creation.

    Args:
        hits: SearchHit objects returned by every ``search()`` call.
              Defaults to an empty list (no capabilities retrieved —
              useful for testing GAP routing).
    """
    mock_client: MagicMock = MagicMock()
    mock_client.collection_exists.return_value = True
    mock_client.create_collection.return_value = None
    mock_client.delete_collection.return_value = None
    mock_client.upsert.return_value = None
    mock_client.delete.return_value = None

    resolved: list[SearchHit] = hits or []
    mock_points: list[MagicMock] = []
    for h in resolved:
        point: MagicMock = MagicMock()
        point.score = h.score
        point.payload = {**h.payload, "_id": h.id}
        point.id = str(h.id)
        mock_points.append(point)

    mock_response: MagicMock = MagicMock()
    mock_response.points = mock_points
    mock_client.query_points.return_value = mock_response

    return VectorStore("http://localhost:6333", _client=mock_client, registry=CollectorRegistry())


def make_postgres_store(
    *,
    prior_fitments: list[PriorFitment] | None = None,
) -> PostgresStore:
    """Return a mock PostgresStore with all async methods stubbed out.

    ``get_similar_fitments`` returns *prior_fitments* (default ``[]``).
    All write operations succeed silently — no SQL is ever executed.

    Args:
        prior_fitments: PriorFitment rows returned by
                        ``get_similar_fitments()``.  Pass ``[]`` (the
                        default) to simulate Wave 1 where no history
                        exists yet.  Pass a non-empty list to test that
                        Phase 4 routes to FAST_TRACK when history is
                        present.
    """
    store: MagicMock = MagicMock(spec=PostgresStore)
    store.ensure_schema = AsyncMock()
    store.save_upload = AsyncMock()
    store.update_upload_status = AsyncMock()
    store.save_fitment = AsyncMock()
    store.get_similar_fitments = AsyncMock(return_value=prior_fitments or [])
    store.dispose = AsyncMock()
    return cast(PostgresStore, store)


def make_redis_pub_sub(events: list[Any] | None = None) -> RedisPubSub:
    """Return a mock RedisPubSub with stubbed publish and subscribe.

    ``publish`` is an ``AsyncMock`` no-op.  ``subscribe`` is an async
    generator that yields *events* in order then stops — the WebSocket
    handler sees a normal event stream without a real Redis connection.

    Args:
        events: ProgressEvent instances emitted by ``subscribe()``.
                Defaults to an empty sequence (subscriber exits
                immediately, simulating a completed or silent pipeline).
    """
    pub: MagicMock = MagicMock(spec=RedisPubSub)
    pub.publish = AsyncMock()
    pub.close = AsyncMock()

    resolved_events: list[Any] = list(events or [])

    async def _subscribe(batch_id: str) -> AsyncGenerator[Any, None]:
        for event in resolved_events:
            yield event

    pub.subscribe = _subscribe
    return cast(RedisPubSub, pub)


# ---------------------------------------------------------------------------
# Schema factories
# ---------------------------------------------------------------------------


def make_product_config(**overrides: Any) -> ProductConfig:
    """Return a valid D365 F&O ProductConfig, patched by *overrides*."""
    defaults: dict[str, Any] = {
        "product_id": "d365_fo",
        "display_name": "Dynamics 365 Finance & Operations",
        "llm_model": "claude-sonnet-4-6",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "capability_kb_namespace": "d365_fo_capabilities",
        "doc_corpus_namespace": "d365_fo_docs",
        "historical_fitments_table": "d365_fo_fitments",
        "fit_confidence_threshold": 0.85,
        "review_confidence_threshold": 0.60,
        "auto_approve_with_history": True,
        "country_rules_path": "knowledge_bases/d365_fo/country_rules/",
        "fdd_template_path": "knowledge_bases/d365_fo/fdd_templates/fit_template.j2",
        "code_language": "xpp",
    }
    defaults.update(overrides)
    return ProductConfig(**defaults)


def make_raw_upload(**overrides: Any) -> RawUpload:
    """Return a valid RawUpload for a PDF requirements document."""
    defaults: dict[str, Any] = {
        "upload_id": "upload-test-001",
        "filename": "requirements.pdf",
        "file_bytes": b"%PDF-1.4",
        "product_id": "d365_fo",
        "country": "DE",
        "wave": 1,
    }
    defaults.update(overrides)
    return RawUpload(**defaults)


def make_requirement_atom(**overrides: Any) -> RequirementAtom:
    """Return a valid RequirementAtom extracted from a table row."""
    defaults: dict[str, Any] = {
        "atom_id": "REQ-AP-001",
        "upload_id": "upload-test-001",
        "requirement_text": ("System must support three-way matching for purchase invoices."),
        "content_type": "text",
    }
    defaults.update(overrides)
    return RequirementAtom(**defaults)


def make_validated_atom(**overrides: Any) -> ValidatedAtom:
    """Return a valid ValidatedAtom that has passed all Phase 1 quality gates."""
    defaults: dict[str, Any] = {
        "atom_id": "REQ-AP-001",
        "upload_id": "upload-test-001",
        "requirement_text": ("System must support three-way matching for purchase invoices."),
        "module": "AccountsPayable",
        "country": "DE",
        "wave": 1,
        "intent": "FUNCTIONAL",
        "specificity_score": 0.85,
        "completeness_score": 80.0,
    }
    defaults.update(overrides)
    return ValidatedAtom(**defaults)


def make_ranked_capability(**overrides: Any) -> RankedCapability:
    """Return a valid RankedCapability from Source A (D365 capability KB)."""
    defaults: dict[str, Any] = {
        "capability_id": "cap-ap-0001",
        "feature": "Three-way matching",
        "description": (
            "Validates purchase order, product receipt, and vendor invoice "
            "quantities and amounts before payment approval."
        ),
        "navigation": "AP > Invoices > Invoice matching",
        "module": "AccountsPayable",
        "version": "10.0.38",
        "composite_score": 0.91,
        "rerank_score": 0.88,
        "bm25_score": 0.72,
    }
    defaults.update(overrides)
    return RankedCapability(**defaults)


def make_prior_fitment(**overrides: Any) -> PriorFitment:
    """Return a valid PriorFitment from Source C (pgvector historical fitments)."""
    defaults: dict[str, Any] = {
        "atom_id": "REQ-AP-001",
        "wave": 1,
        "country": "DE",
        "classification": "FIT",
        "confidence": 0.92,
        "rationale": "D365 standard AP module supports three-way matching natively.",
        "reviewer_override": False,
        "consultant": None,
    }
    defaults.update(overrides)
    return PriorFitment(**defaults)


def make_classification_result(**overrides: Any) -> ClassificationResult:
    """Return a valid Phase 4 ClassificationResult."""
    defaults: dict[str, Any] = {
        "atom_id": "REQ-AP-001",
        "requirement_text": ("System must support three-way matching for purchase invoices."),
        "module": "AccountsPayable",
        "country": "DE",
        "wave": 1,
        "classification": FitLabel.FIT,
        "confidence": 0.92,
        "rationale": "D365 standard AP module supports three-way matching natively.",
        "d365_capability_ref": "cap-ap-0001",
        "route_used": RouteLabel.FAST_TRACK,
        "llm_calls_used": 1,
    }
    defaults.update(overrides)
    return ClassificationResult(**defaults)


def make_assembled_context(**overrides: Any) -> AssembledContext:
    """Return a valid AssembledContext ready for Phase 3 / Phase 4 processing.

    ``provenance_hash`` is computed from the atom ID and capability IDs so
    golden fixture tests can reproduce a stable hash without overriding it.
    Pass ``provenance_hash=<your_value>`` in *overrides* to fix it for a
    specific golden fixture.
    """
    atom: ValidatedAtom = overrides.pop("atom", None) or make_validated_atom()
    capabilities: list[RankedCapability] = overrides.pop("capabilities", None) or [
        make_ranked_capability()
    ]

    provenance_hash: str = hashlib.sha256(
        (atom.atom_id + "".join(c.capability_id for c in capabilities)).encode()
    ).hexdigest()

    defaults: dict[str, Any] = {
        "atom": atom,
        "capabilities": capabilities,
        "ms_learn_refs": [],
        "prior_fitments": [],
        "retrieval_confidence": "HIGH",
        "retrieval_latency_ms": 42.0,
        "sources_available": ["qdrant"],
        "provenance_hash": provenance_hash,
    }
    defaults.update(overrides)
    return AssembledContext(**defaults)


def make_match_result(**overrides: Any) -> MatchResult:
    """Return a valid Phase 3 MatchResult (the input to Phase 4 classification).

    ``composite_scores`` defaults to one score per capability, aligned by
    index as required by ``MatchResult``'s model validator.
    """
    atom: ValidatedAtom = overrides.pop("atom", None) or make_validated_atom()
    capabilities: list[RankedCapability] = overrides.pop("ranked_capabilities", None) or [
        make_ranked_capability()
    ]
    scores: list[float] = overrides.pop("composite_scores", None) or [0.91] * len(capabilities)

    defaults: dict[str, Any] = {
        "atom": atom,
        "ranked_capabilities": capabilities,
        "composite_scores": scores,
        "route": RouteLabel.FAST_TRACK,
        "top_composite_score": max(scores) if scores else 0.0,
        "anomaly_flags": [],
    }
    defaults.update(overrides)
    return MatchResult(**defaults)


def make_search_hit(**overrides: Any) -> SearchHit:
    """Return a valid SearchHit as returned by ``VectorStore.search()``.

    Useful when configuring ``make_vector_store(hits=[make_search_hit(...)])``.
    """
    id_val: str | int = overrides.pop("id", "cap-ap-0001")
    score_val: float = overrides.pop("score", 0.91)
    payload_val: dict[str, Any] = overrides.pop(
        "payload",
        {"module": "AccountsPayable", "feature": "Three-way matching"},
    )
    return SearchHit(id=id_val, score=score_val, payload=payload_val)
