"""
Tests for platform/schemas/retrieval.py.

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

# ---------------------------------------------------------------------------
# Shared fixture builders
# ---------------------------------------------------------------------------

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

_DENSE = [0.1] * 1024


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


def _doc_ref() -> DocReference:
    return DocReference(
        url="https://learn.microsoft.com/en-us/dynamics365/finance/ap/",
        title="AP overview",
        excerpt="Three-way matching validates...",
        score=0.72,
    )


def _prior() -> PriorFitment:
    return PriorFitment(
        atom_id="a-prev",
        wave=1,
        country="FR",
        classification="FIT",
        confidence=0.92,
        rationale="Standard D365 three-way matching covers this.",
    )


# ---------------------------------------------------------------------------
# RetrievalQuery
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetrievalQuery:
    def test_creates_valid(self) -> None:
        q = RetrievalQuery(atom_id="a-001", dense_vector=_DENSE)
        assert q.atom_id == "a-001"
        assert len(q.dense_vector) == 1024

    def test_defaults(self) -> None:
        q = RetrievalQuery(atom_id="a-001", dense_vector=_DENSE)
        assert q.top_k == 20
        assert q.is_image_derived is False
        assert q.sparse_tokens == []
        assert q.metadata_filter == {}

    def test_empty_dense_vector_raises(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalQuery(atom_id="a-001", dense_vector=[])

    def test_top_k_too_small_raises(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalQuery(atom_id="a-001", dense_vector=_DENSE, top_k=0)

    def test_top_k_too_large_raises(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalQuery(atom_id="a-001", dense_vector=_DENSE, top_k=101)

    def test_metadata_filter_stored(self) -> None:
        q = RetrievalQuery(
            atom_id="a-001",
            dense_vector=_DENSE,
            metadata_filter={"module": "AccountsPayable", "version": "10.0.38"},
        )
        assert q.metadata_filter["module"] == "AccountsPayable"

    def test_image_derived_flag(self) -> None:
        q = RetrievalQuery(atom_id="a-1", dense_vector=_DENSE, is_image_derived=True)
        assert q.is_image_derived is True

    def test_frozen(self) -> None:
        q = RetrievalQuery(atom_id="a-1", dense_vector=_DENSE)
        with pytest.raises(ValidationError):
            q.atom_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RankedCapability
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRankedCapability:
    def test_creates_valid(self) -> None:
        c = _cap()
        assert c.capability_id == "cap-ap-0001"
        assert c.feature == "Three-way matching"

    def test_composite_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            _cap(composite_score=1.1)

    def test_rerank_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            _cap(rerank_score=-0.1)

    def test_defaults(self) -> None:
        c = _cap()
        assert c.navigation == ""
        assert c.version == ""
        assert c.tags == []

    def test_tags_stored(self) -> None:
        c = _cap(tags=["invoice", "matching"])
        assert c.tags == ["invoice", "matching"]

    def test_frozen(self) -> None:
        c = _cap()
        with pytest.raises(ValidationError):
            c.feature = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DocReference
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDocReference:
    def test_creates_valid(self) -> None:
        d = _doc_ref()
        assert d.title == "AP overview"

    def test_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            DocReference(
                url="https://example.com",
                title="T",
                excerpt="E",
                score=1.5,
            )

    def test_frozen(self) -> None:
        d = _doc_ref()
        with pytest.raises(ValidationError):
            d.title = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PriorFitment
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPriorFitment:
    def test_creates_valid(self) -> None:
        p = _prior()
        assert p.classification == "FIT"
        assert p.reviewer_override is False

    def test_all_valid_classifications(self) -> None:
        for cls in ("FIT", "PARTIAL_FIT", "GAP"):
            p = PriorFitment(
                atom_id="a",
                wave=1,
                country="DE",
                classification=cls,  # type: ignore[arg-type]
                confidence=0.9,
                rationale="reason",
            )
            assert p.classification == cls

    def test_invalid_classification_raises(self) -> None:
        with pytest.raises(ValidationError):
            PriorFitment(
                atom_id="a",
                wave=1,
                country="DE",
                classification="REVIEW_REQUIRED",  # type: ignore[arg-type]
                confidence=0.9,
                rationale="r",
            )

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            PriorFitment(
                atom_id="a",
                wave=1,
                country="DE",
                classification="FIT",
                confidence=1.1,
                rationale="r",
            )

    def test_reviewer_override_and_consultant(self) -> None:
        p = PriorFitment(
            atom_id="a",
            wave=2,
            country="DE",
            classification="FIT",
            confidence=0.95,
            rationale="consultant confirmed",
            reviewer_override=True,
            consultant="jane@example.com",
        )
        assert p.reviewer_override is True
        assert p.consultant == "jane@example.com"

    def test_wave_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            PriorFitment(
                atom_id="a",
                wave=0,
                country="DE",
                classification="FIT",
                confidence=0.9,
                rationale="r",
            )

    def test_frozen(self) -> None:
        p = _prior()
        with pytest.raises(ValidationError):
            p.classification = "GAP"  # type: ignore[misc]


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

    def test_creates_valid(self) -> None:
        ctx = self._make()
        assert ctx.retrieval_confidence == "HIGH"

    def test_defaults(self) -> None:
        ctx = self._make()
        assert ctx.ms_learn_refs == []
        assert ctx.prior_fitments == []
        assert ctx.sources_available == []

    def test_invalid_confidence_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(retrieval_confidence="VERY_HIGH")

    def test_negative_latency_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(retrieval_latency_ms=-1.0)

    def test_atom_accessible(self) -> None:
        ctx = self._make()
        assert ctx.atom.atom_id == "a-001"

    def test_with_prior_fitments(self) -> None:
        ctx = self._make(prior_fitments=[_prior()])
        assert len(ctx.prior_fitments) == 1
        assert ctx.prior_fitments[0].classification == "FIT"

    def test_frozen(self) -> None:
        ctx = self._make()
        with pytest.raises(ValidationError):
            ctx.retrieval_confidence = "LOW"  # type: ignore[misc]
