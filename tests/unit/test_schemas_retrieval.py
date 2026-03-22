"""
Tests for platform/schemas/retrieval.py — validation boundaries only.

Covers: RetrievalQuery, RankedCapability, DocReference, PriorFitment, AssembledContext.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform.schemas.requirement import ValidatedAtom
from platform.schemas.retrieval import (
    AssembledContext,
    DocReference,
    PriorFitment,
    RankedCapability,
    RetrievalQuery,
)

_VALID_ATOM_KWARGS = {
    "atom_id": "a-001",
    "upload_id": "u-001",
    "requirement_text": "The system shall validate three-way matching for vendor invoices.",
    "module": "AccountsPayable",
    "country": "DE",
    "wave": 1,
    "intent": "FUNCTIONAL",
    "specificity_score": 0.85,
    "completeness_score": 60.0,
}

_DENSE = [0.1] * 384


def _atom() -> ValidatedAtom:
    return ValidatedAtom(**_VALID_ATOM_KWARGS)


def _cap(**overrides: object) -> RankedCapability:
    kwargs = {
        "capability_id": "cap-ap-0001",
        "feature": "Three-way matching",
        "description": "Validates PO, receipt, and vendor invoice.",
        "module": "AccountsPayable",
        "composite_score": 0.88,
        "rerank_score": 0.91,
    }
    kwargs.update(overrides)
    return RankedCapability(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RetrievalQuery
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetrievalQuery:
    def test_empty_dense_vector_raises(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalQuery(atom_id="a-001", dense_vector=[])

    def test_top_k_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalQuery(atom_id="a-001", dense_vector=_DENSE, top_k=0)
        with pytest.raises(ValidationError):
            RetrievalQuery(atom_id="a-001", dense_vector=_DENSE, top_k=101)


# ---------------------------------------------------------------------------
# RankedCapability
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRankedCapability:
    def test_composite_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            _cap(composite_score=1.1)

    def test_rerank_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            _cap(rerank_score=-0.1)


# ---------------------------------------------------------------------------
# DocReference
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_doc_reference_score_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        DocReference(url="https://example.com", title="T", excerpt="E", score=1.5)


# ---------------------------------------------------------------------------
# PriorFitment
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPriorFitment:
    def test_invalid_classification_raises(self) -> None:
        with pytest.raises(ValidationError):
            PriorFitment(
                atom_id="a", wave=1, country="DE",
                classification="REVIEW_REQUIRED",  # type: ignore[arg-type]
                confidence=0.9, rationale="r",
            )

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            PriorFitment(
                atom_id="a", wave=1, country="DE",
                classification="FIT", confidence=1.1, rationale="r",
            )

    def test_wave_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            PriorFitment(
                atom_id="a", wave=0, country="DE",
                classification="FIT", confidence=0.9, rationale="r",
            )


# ---------------------------------------------------------------------------
# AssembledContext
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAssembledContext:
    def _make(self, **overrides: object) -> AssembledContext:
        kwargs: dict[str, object] = {
            "atom": _atom(),
            "capabilities": [_cap()],
            "retrieval_confidence": "HIGH",
            "retrieval_latency_ms": 123.4,
            "provenance_hash": "abc123",
        }
        kwargs.update(overrides)
        return AssembledContext(**kwargs)  # type: ignore[arg-type]

    def test_invalid_confidence_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(retrieval_confidence="VERY_HIGH")

    def test_negative_latency_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(retrieval_latency_ms=-1.0)
