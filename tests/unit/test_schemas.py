"""
Consolidated schema validation tests — one per business rule that matters.

Tests Pydantic-level invariants that protect data integrity at system boundaries.
Cuts: frozen, defaults, whitespace, creates_valid, every-field-rejection.
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
from platform.schemas.requirement import RawUpload, ValidatedAtom
from platform.schemas.retrieval import RankedCapability

_VALID_ATOM = {
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

_VALID_CAP = {
    "capability_id": "cap-ap-0001",
    "feature": "Three-way matching",
    "description": "Validates PO, receipt, and vendor invoice.",
    "module": "AccountsPayable",
    "composite_score": 0.88,
    "rerank_score": 0.91,
}

_VALID_RESULT = {
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


# ---------------------------------------------------------------------------
# MatchResult: scores-must-match-capabilities (business invariant)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_match_result_scores_must_match_capabilities() -> None:
    atom = ValidatedAtom(**_VALID_ATOM)
    cap = RankedCapability(**_VALID_CAP)
    with pytest.raises(ValidationError):
        MatchResult(
            atom=atom,
            ranked_capabilities=[cap, cap],
            composite_scores=[0.88],  # length mismatch
            route=RouteLabel.FAST_TRACK,
            top_composite_score=0.88,
        )


# ---------------------------------------------------------------------------
# ValidatedFitmentBatch: counts-must-sum-to-total (business invariant)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_batch_counts_must_sum_to_total() -> None:
    result = ClassificationResult(**_VALID_RESULT)
    with pytest.raises(ValidationError):
        ValidatedFitmentBatch(
            batch_id="b-001",
            upload_id="u-001",
            product_id="d365_fo",
            wave=1,
            results=[result],
            total_atoms=5,
            fit_count=2,
            partial_fit_count=1,
            gap_count=1,
            review_count=0,  # sum=4 != 5
        )


# ---------------------------------------------------------------------------
# ProductConfig: review < fit threshold (business rule)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_review_threshold_must_be_less_than_fit() -> None:
    from platform.schemas.product import ProductConfig

    base = {
        "product_id": "d365_fo",
        "display_name": "D365 F&O",
        "llm_model": "claude-sonnet-4-6",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "capability_kb_namespace": "d365_fo_capabilities",
        "doc_corpus_namespace": "d365_fo_docs",
        "historical_fitments_table": "d365_fo_fitments",
        "auto_approve_with_history": True,
        "country_rules_path": "kb/rules",
        "fdd_template_path": "kb/tpl.j2",
        "code_language": "xpp",
    }
    with pytest.raises(ValidationError):
        ProductConfig(
            **base,
            fit_confidence_threshold=0.70,
            review_confidence_threshold=0.80,
        )


# ---------------------------------------------------------------------------
# ProgressEvent discriminated union (core business logic)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_progress_event_union_resolves_all_types() -> None:
    from datetime import UTC, datetime

    from pydantic import TypeAdapter

    from platform.schemas.events import (
        ClassificationEvent,
        CompleteEvent,
        ErrorEvent,
        PhaseStartEvent,
        ProgressEvent,
        StepProgressEvent,
    )

    ta = TypeAdapter(ProgressEvent)
    ts = datetime.now(UTC).isoformat()

    assert isinstance(
        ta.validate_python({"event": "phase_start", "batch_id": "b", "phase": 1,
                            "phase_name": "X", "timestamp": ts}),
        PhaseStartEvent,
    )
    assert isinstance(
        ta.validate_python({"event": "step_progress", "batch_id": "b", "phase": 1,
                            "step": "s", "completed": 1, "total": 10, "timestamp": ts}),
        StepProgressEvent,
    )
    assert isinstance(
        ta.validate_python({"event": "classification", "batch_id": "b", "atom_id": "a",
                            "classification": "FIT", "confidence": 0.9, "timestamp": ts}),
        ClassificationEvent,
    )
    assert isinstance(
        ta.validate_python({"event": "complete", "batch_id": "b", "total": 10,
                            "fit_count": 7, "partial_fit_count": 2, "gap_count": 1,
                            "review_count": 0, "timestamp": ts}),
        CompleteEvent,
    )
    assert isinstance(
        ta.validate_python({"event": "error", "batch_id": "b", "error_type": "E",
                            "message": "m", "timestamp": ts}),
        ErrorEvent,
    )
    with pytest.raises(ValidationError):
        ta.validate_python({"event": "unknown_event", "batch_id": "b"})


# ---------------------------------------------------------------------------
# Errors: catchable + structured fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_platform_errors_are_catchable_with_fields() -> None:
    from platform.schemas.errors import ParseError, RetrievalError, UnsupportedFormatError

    with pytest.raises(UnsupportedFormatError) as exc:
        raise UnsupportedFormatError(filename="d.bin", detected_mime="application/octet-stream")
    assert exc.value.filename == "d.bin"

    with pytest.raises(ParseError) as exc2:
        raise ParseError(filename="r.pdf", reason="col not found")
    assert exc2.value.filename == "r.pdf"

    with pytest.raises(RetrievalError) as exc3:
        raise RetrievalError(source="qdrant", atom_id="a-1", reason="timeout")
    assert exc3.value.source == "qdrant"


# ---------------------------------------------------------------------------
# ValidatedAtom: key boundary (module whitelist + score range)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validated_atom_rejects_invalid_module_and_score() -> None:
    with pytest.raises(ValidationError):
        ValidatedAtom(**{**_VALID_ATOM, "module": "FakeModule"})
    with pytest.raises(ValidationError):
        ValidatedAtom(**{**_VALID_ATOM, "specificity_score": 1.5})


# ---------------------------------------------------------------------------
# RawUpload: wave must be positive
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_raw_upload_wave_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        RawUpload(upload_id="u-1", filename="f.pdf", file_bytes=b"x", product_id="d365_fo", wave=0)
