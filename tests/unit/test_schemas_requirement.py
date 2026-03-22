"""
Tests for platform/schemas/requirement.py — validation boundary tests only.

Covers: RawUpload, RequirementAtom, ValidatedAtom, FlaggedAtom.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform.schemas.requirement import (
    FlaggedAtom,
    RawUpload,
    RequirementAtom,
    ValidatedAtom,
)


# ---------------------------------------------------------------------------
# RawUpload
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawUpload:
    def test_wave_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            RawUpload(
                upload_id="u-1", filename="f.pdf", file_bytes=b"x", product_id="d365_fo", wave=0
            )

    def test_empty_filename_raises(self) -> None:
        with pytest.raises(ValidationError):
            RawUpload(upload_id="u-1", filename="", file_bytes=b"x", product_id="d365_fo")


# ---------------------------------------------------------------------------
# RequirementAtom
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRequirementAtom:
    def test_empty_requirement_text_raises(self) -> None:
        with pytest.raises(ValidationError):
            RequirementAtom(atom_id="a-1", upload_id="u-1", requirement_text="")

    def test_invalid_content_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            RequirementAtom(
                atom_id="a-1",
                upload_id="u-1",
                requirement_text="text",
                content_type="video",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# ValidatedAtom
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidatedAtom:
    _VALID = {
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

    def test_invalid_module_raises(self) -> None:
        with pytest.raises(ValidationError):
            ValidatedAtom(**{**self._VALID, "module": "FakeModule"})

    def test_specificity_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ValidatedAtom(**{**self._VALID, "specificity_score": 1.5})

    def test_completeness_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ValidatedAtom(**{**self._VALID, "completeness_score": 101.0})

    def test_invalid_intent_raises(self) -> None:
        with pytest.raises(ValidationError):
            ValidatedAtom(**{**self._VALID, "intent": "UNKNOWN"})  # type: ignore[arg-type]

    def test_requirement_text_too_short_raises(self) -> None:
        with pytest.raises(ValidationError):
            ValidatedAtom(**{**self._VALID, "requirement_text": "Too short"})

    def test_wave_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            ValidatedAtom(**{**self._VALID, "wave": 0})


# ---------------------------------------------------------------------------
# FlaggedAtom
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFlaggedAtom:
    _VALID = {
        "atom_id": "a-bad",
        "upload_id": "u-001",
        "requirement_text": "The system should handle stuff.",
        "flag_reason": "TOO_VAGUE",
        "flag_detail": "specificity_score=0.18, below threshold 0.30",
        "specificity_score": 0.18,
    }

    def test_invalid_flag_reason_raises(self) -> None:
        with pytest.raises(ValidationError):
            FlaggedAtom(  # type: ignore[arg-type]
                **{**self._VALID, "flag_reason": "WRONG_REASON"}
            )

    def test_specificity_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            FlaggedAtom(**{**self._VALID, "specificity_score": -0.1})
