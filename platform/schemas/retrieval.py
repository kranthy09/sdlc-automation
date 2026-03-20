"""
Retrieval pipeline schemas — the data shapes for Phase 2 (Knowledge Retrieval).

Pipeline:
  ValidatedAtom → RetrievalQuery → [Qdrant + pgvector + MS Learn]
               → RankedCapability[] + DocReference[] + PriorFitment[]
               → AssembledContext  (handed to Phase 3)

RetrievalQuery     — query signals built from a ValidatedAtom
RankedCapability   — a D365 capability hit from Source A (capability KB),
                     scored by cross-encoder reranker
DocReference       — a MS Learn documentation chunk hit from Source B
PriorFitment       — a historical fitment decision from Source C (pgvector)
AssembledContext   — all retrieval outputs packaged for Phase 3/4
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .base import PlatformModel
from .requirement import ValidatedAtom

# ---------------------------------------------------------------------------
# RetrievalQuery
# ---------------------------------------------------------------------------


class RetrievalQuery(PlatformModel):
    """Retrieval signals generated from a ValidatedAtom for parallel search."""

    atom_id: str

    # Dense embedding vector (bge-large-en-v1.5, 1024-dim)
    dense_vector: Annotated[list[float], Field(min_length=1)]

    # Sparse tokens for BM25 retrieval
    sparse_tokens: list[str] = Field(default_factory=list)

    # Qdrant payload filter (e.g. {"module": "AccountsPayable"})
    metadata_filter: dict[str, str | int | float | bool] = Field(default_factory=dict)

    # Number of capabilities to retrieve before reranking
    top_k: Annotated[int, Field(ge=1, le=100)] = 20

    # Image-derived atoms cast a wider net (top_k=30 per spec)
    is_image_derived: bool = False


# ---------------------------------------------------------------------------
# RankedCapability
# ---------------------------------------------------------------------------


class RankedCapability(PlatformModel):
    """A D365 capability retrieved from Source A and scored by the reranker."""

    capability_id: str
    feature: str
    description: str
    navigation: str = ""
    module: str
    version: str = ""
    tags: list[str] = Field(default_factory=list)

    # Weighted composite score from Phase 3 (embedding + entity + token + history + rerank)
    composite_score: Annotated[float, Field(ge=0.0, le=1.0)]

    # Cross-encoder score: sigmoid(logit) from ms-marco-MiniLM
    rerank_score: Annotated[float, Field(ge=0.0, le=1.0)]

    # BM25 sparse retrieval contribution
    bm25_score: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0


# ---------------------------------------------------------------------------
# DocReference
# ---------------------------------------------------------------------------


class DocReference(PlatformModel):
    """A MS Learn documentation chunk retrieved from Source B."""

    url: str
    title: str
    excerpt: str
    score: Annotated[float, Field(ge=0.0, le=1.0)]


# ---------------------------------------------------------------------------
# PriorFitment
# ---------------------------------------------------------------------------


class PriorFitment(PlatformModel):
    """A historical fitment decision retrieved from Source C (pgvector).

    Consultant overrides (reviewer_override=True) are the highest-quality
    signal — Phase 4 treats them as strong classification evidence.
    """

    atom_id: str
    wave: Annotated[int, Field(ge=1)]
    country: str
    classification: Literal["FIT", "PARTIAL_FIT", "GAP"]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    rationale: str

    # True when a consultant manually overrode the AI classification
    reviewer_override: bool = False
    consultant: str | None = None


# ---------------------------------------------------------------------------
# AssembledContext
# ---------------------------------------------------------------------------


class AssembledContext(PlatformModel):
    """All retrieval outputs assembled for Phase 3 (Semantic Matching) / Phase 4 (Classification).

    provenance_hash is SHA-256 of all inputs (atom text + capability IDs + prior fitment IDs)
    — used for audit trail and golden fixture comparison in tests.
    """

    atom: ValidatedAtom
    capabilities: list[RankedCapability]
    ms_learn_refs: list[DocReference] = Field(default_factory=list)
    prior_fitments: list[PriorFitment] = Field(default_factory=list)

    retrieval_confidence: Literal["HIGH", "MEDIUM", "LOW"]
    retrieval_latency_ms: Annotated[float, Field(ge=0.0)]

    # Which sources returned results (e.g. ["qdrant", "ms_learn", "pgvector"])
    sources_available: list[str] = Field(default_factory=list)

    # SHA-256 of all inputs — for audit trail and golden fixture replay
    provenance_hash: str
