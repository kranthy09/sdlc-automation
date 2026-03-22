"""
Tests for platform/schemas/fitment.py — business-rule validation only.

Covers: MatchResult scores-must-match-capabilities, ClassificationResult validation,
ValidatedFitmentBatch counts-must-sum-to-total.
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

    def test_scores_must_match_capabilities_length(self) -> None:
        """Business invariant: one score per capability."""
        with pytest.raises(ValidationError):
            self._make(
                ranked_capabilities=[_cap(), _cap()],
                composite_scores=[0.88],  # length mismatch
            )

    def test_top_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(top_composite_score=1.5)

    def test_invalid_route_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(route="UNKNOWN_ROUTE")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ClassificationResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassificationResult:
    def test_creates_valid(self) -> None:
        r = ClassificationResult(**_VALID_RESULT_KWARGS)
        assert r.classification == FitLabel.FIT
        assert r.confidence == 0.91

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClassificationResult(**{**_VALID_RESULT_KWARGS, "confidence": 1.1})

    def test_dev_effort_invalid_value_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClassificationResult(**{**_VALID_RESULT_KWARGS, "dev_effort": "XL"})

    def test_llm_calls_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClassificationResult(**{**_VALID_RESULT_KWARGS, "llm_calls_used": 0})

    def test_wave_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClassificationResult(**{**_VALID_RESULT_KWARGS, "wave": 0})

    def test_gap_fields_round_trip(self) -> None:
        """GAP-specific fields (dev_effort, gap_type) survive round-trip."""
        r = ClassificationResult(
            **{
                **_VALID_RESULT_KWARGS,
                "classification": FitLabel.GAP,
                "dev_effort": "M",
                "gap_type": "Extension",
            }
        )
        assert r.dev_effort == "M"
        assert r.gap_type == "Extension"


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

    def test_counts_must_sum_to_total(self) -> None:
        """Business invariant: fit + partial + gap + review == total."""
        with pytest.raises(ValidationError):
            self._make(
                total_atoms=5,
                fit_count=2,
                partial_fit_count=1,
                gap_count=1,
                review_count=0,  # sum=4, not 5
            )

    def test_negative_count_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make(
                fit_count=-1, total_atoms=0, partial_fit_count=0, gap_count=0, review_count=0
            )

    def test_mixed_counts_valid(self) -> None:
        """Batch with multiple classification types passes when counts sum correctly."""
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
