"""
Tests for platform/schemas/events.py — WebSocket progress event types.

Covers: PhaseStartEvent, StepProgressEvent, ClassificationEvent,
        CompleteEvent, ErrorEvent, ProgressEvent discriminated union.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from platform.schemas.events import (
    ClassificationEvent,
    CompleteEvent,
    ErrorEvent,
    PhaseStartEvent,
    ProgressEvent,
    StepProgressEvent,
)
from platform.schemas.fitment import FitLabel

# ---------------------------------------------------------------------------
# PhaseStartEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPhaseStartEvent:
    def test_creates_valid(self) -> None:
        e = PhaseStartEvent(batch_id="b-1", phase=1, phase_name="Ingestion")
        assert e.event == "phase_start"
        assert e.phase == 1
        assert e.phase_name == "Ingestion"

    def test_event_field_is_literal(self) -> None:
        e = PhaseStartEvent(batch_id="b-1", phase=2, phase_name="Retrieval")
        assert e.event == "phase_start"

    def test_timestamp_auto_set(self) -> None:
        e = PhaseStartEvent(batch_id="b-1", phase=1, phase_name="Ingestion")
        assert isinstance(e.timestamp, datetime)

    def test_phase_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            PhaseStartEvent(batch_id="b-1", phase=0, phase_name="X")

    def test_phase_above_five_raises(self) -> None:
        with pytest.raises(ValidationError):
            PhaseStartEvent(batch_id="b-1", phase=6, phase_name="X")

    def test_frozen(self) -> None:
        e = PhaseStartEvent(batch_id="b-1", phase=1, phase_name="Ingestion")
        with pytest.raises(ValidationError):
            e.phase = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StepProgressEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStepProgressEvent:
    def test_creates_valid(self) -> None:
        e = StepProgressEvent(
            batch_id="b-1",
            phase=1,
            step="atomizer",
            completed=10,
            total=50,
        )
        assert e.event == "step_progress"
        assert e.completed == 10
        assert e.total == 50

    def test_completed_can_be_zero(self) -> None:
        e = StepProgressEvent(batch_id="b-1", phase=1, step="s", completed=0, total=10)
        assert e.completed == 0

    def test_total_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            StepProgressEvent(batch_id="b-1", phase=1, step="s", completed=0, total=0)

    def test_completed_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            StepProgressEvent(batch_id="b-1", phase=1, step="s", completed=-1, total=10)

    def test_frozen(self) -> None:
        e = StepProgressEvent(batch_id="b-1", phase=1, step="s", completed=5, total=10)
        with pytest.raises(ValidationError):
            e.completed = 6  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ClassificationEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassificationEvent:
    def test_creates_valid(self) -> None:
        e = ClassificationEvent(
            batch_id="b-1",
            atom_id="a-001",
            classification=FitLabel.FIT,
            confidence=0.91,
        )
        assert e.event == "classification"
        assert e.classification == FitLabel.FIT

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClassificationEvent(
                batch_id="b-1",
                atom_id="a-1",
                classification=FitLabel.GAP,
                confidence=1.5,
            )

    def test_all_fit_labels_accepted(self) -> None:
        for label in FitLabel:
            e = ClassificationEvent(
                batch_id="b-1",
                atom_id="a-1",
                classification=label,
                confidence=0.8,
            )
            assert e.classification == label

    def test_frozen(self) -> None:
        e = ClassificationEvent(
            batch_id="b-1",
            atom_id="a-1",
            classification=FitLabel.FIT,
            confidence=0.9,
        )
        with pytest.raises(ValidationError):
            e.confidence = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CompleteEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteEvent:
    def test_creates_valid(self) -> None:
        e = CompleteEvent(
            batch_id="b-1",
            total=50,
            fit_count=36,
            partial_fit_count=7,
            gap_count=7,
            review_count=0,
        )
        assert e.event == "complete"
        assert e.total == 50

    def test_negative_count_raises(self) -> None:
        with pytest.raises(ValidationError):
            CompleteEvent(
                batch_id="b-1",
                total=50,
                fit_count=-1,
                partial_fit_count=7,
                gap_count=7,
                review_count=0,
            )

    def test_report_url_optional(self) -> None:
        e = CompleteEvent(
            batch_id="b-1",
            total=5,
            fit_count=5,
            partial_fit_count=0,
            gap_count=0,
            review_count=0,
        )
        assert e.report_url is None

    def test_frozen(self) -> None:
        e = CompleteEvent(
            batch_id="b-1",
            total=5,
            fit_count=5,
            partial_fit_count=0,
            gap_count=0,
            review_count=0,
        )
        with pytest.raises(ValidationError):
            e.total = 10  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ErrorEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestErrorEvent:
    def test_creates_valid(self) -> None:
        e = ErrorEvent(
            batch_id="b-1",
            error_type="RetrievalError",
            message="Qdrant timed out",
        )
        assert e.event == "error"
        assert e.error_type == "RetrievalError"

    def test_optional_fields_default_none(self) -> None:
        e = ErrorEvent(batch_id="b-1", error_type="ParseError", message="bad file")
        assert e.phase is None
        assert e.atom_id is None

    def test_with_phase_and_atom(self) -> None:
        e = ErrorEvent(
            batch_id="b-1",
            phase=2,
            atom_id="a-001",
            error_type="RetrievalError",
            message="timeout",
        )
        assert e.phase == 2
        assert e.atom_id == "a-001"

    def test_frozen(self) -> None:
        e = ErrorEvent(batch_id="b-1", error_type="E", message="m")
        with pytest.raises(ValidationError):
            e.message = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ProgressEvent discriminated union
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProgressEventUnion:
    _ta: TypeAdapter[ProgressEvent] = TypeAdapter(ProgressEvent)  # type: ignore[type-arg]

    def test_resolves_phase_start(self) -> None:
        data = {
            "event": "phase_start",
            "batch_id": "b-1",
            "phase": 1,
            "phase_name": "Ingestion",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        evt = self._ta.validate_python(data)
        assert isinstance(evt, PhaseStartEvent)

    def test_resolves_step_progress(self) -> None:
        data = {
            "event": "step_progress",
            "batch_id": "b-1",
            "phase": 1,
            "step": "atomizer",
            "completed": 5,
            "total": 50,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        evt = self._ta.validate_python(data)
        assert isinstance(evt, StepProgressEvent)

    def test_resolves_classification(self) -> None:
        data = {
            "event": "classification",
            "batch_id": "b-1",
            "atom_id": "a-1",
            "classification": "FIT",
            "confidence": 0.91,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        evt = self._ta.validate_python(data)
        assert isinstance(evt, ClassificationEvent)

    def test_resolves_complete(self) -> None:
        data = {
            "event": "complete",
            "batch_id": "b-1",
            "total": 50,
            "fit_count": 36,
            "partial_fit_count": 7,
            "gap_count": 7,
            "review_count": 0,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        evt = self._ta.validate_python(data)
        assert isinstance(evt, CompleteEvent)

    def test_resolves_error(self) -> None:
        data = {
            "event": "error",
            "batch_id": "b-1",
            "error_type": "ParseError",
            "message": "column not found",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        evt = self._ta.validate_python(data)
        assert isinstance(evt, ErrorEvent)

    def test_unknown_event_raises(self) -> None:
        data = {
            "event": "unknown_event",
            "batch_id": "b-1",
        }
        with pytest.raises(ValidationError):
            self._ta.validate_python(data)
