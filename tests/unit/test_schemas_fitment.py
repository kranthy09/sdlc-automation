"""
Tests for platform/schemas/fitment.py.

Covers: FitLabel, RouteLabel, MatchResult, ClassificationResult, ValidatedFitmentBatch.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform.schemas.fitment import (
    ClassificationResult,
    FitLabel,
    MatchResult,
    RouteLabel,
    ValidatedFitmentBatch,
)
from platform.schemas.requirement import ValidatedAtom
from platform.schemas.retrieval import RankedCapability

# ---------------------------------------------------------------------------
# Shared fixtures
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

_VALID_CAP_KWARGS = {
    "capability_id": "cap-ap-0001",
    "feature": "Three-way matching",
    "description": "Validates PO, receipt, and vendor invoice.",
    "module": "AccountsPayable",
    "composite_score": 0.88,
    "rerank_score": 0.91,
}

_VALID_RESULT_KWARGS = {
    "atom_id": "a-001",
    "requirement_text": "The system shall validate three-way matching for vendor invoices.",
    "module": "AccountsPayable",
    "country": "DE",
    "wave": 1,
    "classification": FitLabel.FIT,
    "confidence": 0.91,
    "rationale": "Standard D365 three-way matching covers this requirement.",
    "route_used": RouteLabel.FAST_TRACK,
}


def _atom() -> ValidatedAtom:
    return ValidatedAtom(**_VALID_ATOM_KWARGS)


def _cap() -> RankedCapability:
    return RankedCapability(**_VALID_CAP_KWARGS)


# ---------------------------------------------------------------------------
# Enum values
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFitLabel:
    def test_all_values(self) -> None:
        assert FitLabel.FIT == "FIT"
        assert FitLabel.PARTIAL_FIT == "PARTIAL_FIT"
        assert FitLabel.GAP == "GAP"
        assert FitLabel.REVIEW_REQUIRED == "REVIEW_REQUIRED"

    def test_string_coercion(self) -> None:
        result = ClassificationResult(**_VALID_RESULT_KWARGS)
        assert result.classification == FitLabel.FIT


@pytest.mark.unit
class TestRouteLabel:
    def test_all_values(self) -> None:
        assert RouteLabel.FAST_TRACK == "FAST_TRACK"
        assert RouteLabel.DEEP_REASON == "DEEP_REASON"
        assert RouteLabel.GAP_CONFIRM == "GAP_CONFIRM"


# ---------------------------------------------------------------------------
# MatchResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMatchResult:
    def _make(self, **overrides: object) -> MatchResult:
        kwargs: dict[str, object] = {
            "atom": _atom(),
            "ranked_capabilities": [_cap()],
            "composite_scores": [0.88],
            "route": RouteLabel.FAST_TRACK,
            "top_composite_score": 0.88,
        }
        kwargs.update(overrides)
        return MatchResult(**kwargs)  # type: ignore[arg-type]

    def test_creates_valid(self) -> None:
        m = self._make()
        assert m.route == RouteLabel.FAST_TRACK
        assert m.top_composite_score == 0.88

    def test_default_anomaly_flags(self) -> None:
        m = self._make()
        assert m.anomaly_flags == []

    def test_scores_must_match_capabilities_length(self) -> None:
        with pytest.raises(ValidationError):
            self._make(
                ranked_capabilities=[_cap(), _cap()],
                composite_scores=[0.88],  # length mismatch
            )

    def test_scores_empty_when_no_capabilities(self) -> None:
        # zero caps and zero scores is valid
        m = self._make(ranked_capabilities=[], composite_scores=[], top_composite_score=0.0)
        assert len(m.ranked_capabilities) == 0

    def test_top_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(top_composite_score=1.5)

    def test_invalid_route_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(route="UNKNOWN_ROUTE")  # type: ignore[arg-type]

    def test_anomaly_flags_stored(self) -> None:
        m = self._make(anomaly_flags=["cosine_entity_mismatch"])
        assert m.anomaly_flags == ["cosine_entity_mismatch"]

    def test_frozen(self) -> None:
        m = self._make()
        with pytest.raises(ValidationError):
            m.route = RouteLabel.GAP_CONFIRM  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ClassificationResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassificationResult:
    def test_creates_valid(self) -> None:
        r = ClassificationResult(**_VALID_RESULT_KWARGS)
        assert r.classification == FitLabel.FIT
        assert r.confidence == 0.91

    def test_all_fit_labels_accepted(self) -> None:
        for label in FitLabel:
            r = ClassificationResult(**{**_VALID_RESULT_KWARGS, "classification": label})
            assert r.classification == label

    def test_all_route_labels_accepted(self) -> None:
        for route in RouteLabel:
            r = ClassificationResult(**{**_VALID_RESULT_KWARGS, "route_used": route})
            assert r.route_used == route

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClassificationResult(**{**_VALID_RESULT_KWARGS, "confidence": 1.1})

    def test_optional_fields_default_none(self) -> None:
        r = ClassificationResult(**_VALID_RESULT_KWARGS)
        assert r.d365_capability_ref is None
        assert r.config_steps is None
        assert r.gap_description is None
        assert r.caveats is None

    def test_llm_calls_default(self) -> None:
        r = ClassificationResult(**_VALID_RESULT_KWARGS)
        assert r.llm_calls_used == 1

    def test_llm_calls_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClassificationResult(**{**_VALID_RESULT_KWARGS, "llm_calls_used": 0})

    def test_wave_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClassificationResult(**{**_VALID_RESULT_KWARGS, "wave": 0})

    def test_frozen(self) -> None:
        r = ClassificationResult(**_VALID_RESULT_KWARGS)
        with pytest.raises(ValidationError):
            r.classification = FitLabel.GAP  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ValidatedFitmentBatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidatedFitmentBatch:
    def _result(self, classification: FitLabel = FitLabel.FIT) -> ClassificationResult:
        return ClassificationResult(**{**_VALID_RESULT_KWARGS, "classification": classification})

    def _make(self, **overrides: object) -> ValidatedFitmentBatch:
        kwargs: dict[str, object] = {
            "batch_id": "batch-001",
            "upload_id": "u-001",
            "product_id": "d365_fo",
            "wave": 1,
            "results": [self._result(FitLabel.FIT)],
            "total_atoms": 1,
            "fit_count": 1,
            "partial_fit_count": 0,
            "gap_count": 0,
            "review_count": 0,
        }
        kwargs.update(overrides)
        return ValidatedFitmentBatch(**kwargs)  # type: ignore[arg-type]

    def test_creates_valid(self) -> None:
        b = self._make()
        assert b.batch_id == "batch-001"
        assert b.fit_count == 1

    def test_counts_must_sum_to_total(self) -> None:
        with pytest.raises(ValidationError):
            self._make(
                total_atoms=5,
                fit_count=2,
                partial_fit_count=1,
                gap_count=1,
                review_count=0,  # sum=4, not 5
            )

    def test_counts_can_be_zero(self) -> None:
        b = self._make(
            results=[],
            total_atoms=0,
            fit_count=0,
            partial_fit_count=0,
            gap_count=0,
            review_count=0,
        )
        assert b.total_atoms == 0

    def test_mixed_counts(self) -> None:
        results = [
            self._result(FitLabel.FIT),
            self._result(FitLabel.PARTIAL_FIT),
            self._result(FitLabel.GAP),
        ]
        b = self._make(
            results=results,
            total_atoms=3,
            fit_count=1,
            partial_fit_count=1,
            gap_count=1,
            review_count=0,
        )
        assert b.total_atoms == 3

    def test_negative_count_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(
                fit_count=-1, total_atoms=0, partial_fit_count=0, gap_count=0, review_count=0
            )

    def test_report_path_default_none(self) -> None:
        b = self._make()
        assert b.report_path is None

    def test_completed_at_default_none(self) -> None:
        b = self._make()
        assert b.completed_at is None

    def test_frozen(self) -> None:
        b = self._make()
        with pytest.raises(ValidationError):
            b.batch_id = "other"  # type: ignore[misc]
