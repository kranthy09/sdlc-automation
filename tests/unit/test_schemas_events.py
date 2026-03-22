"""
Tests for platform/schemas/events.py — WebSocket progress event types.

Keeps: discriminated union resolution (core business logic), key validation boundaries.
Cuts: frozen, defaults, creates_valid, enum iteration.
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
# Validation boundaries
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_phase_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        PhaseStartEvent(batch_id="b-1", phase=0, phase_name="X")
    with pytest.raises(ValidationError):
        PhaseStartEvent(batch_id="b-1", phase=6, phase_name="X")


@pytest.mark.unit
def test_step_progress_total_zero_raises() -> None:
    with pytest.raises(ValidationError):
        StepProgressEvent(batch_id="b-1", phase=1, step="s", completed=0, total=0)


@pytest.mark.unit
def test_classification_confidence_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        ClassificationEvent(
            batch_id="b-1", atom_id="a-1",
            classification=FitLabel.GAP, confidence=1.5,
        )


@pytest.mark.unit
def test_complete_event_negative_count_raises() -> None:
    with pytest.raises(ValidationError):
        CompleteEvent(
            batch_id="b-1", total=50, fit_count=-1,
            partial_fit_count=7, gap_count=7, review_count=0,
        )


# ---------------------------------------------------------------------------
# Discriminated union — core business logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProgressEventUnion:
    """ProgressEvent must correctly resolve each event type by discriminator."""

    _ta: TypeAdapter[ProgressEvent] = TypeAdapter(ProgressEvent)  # type: ignore[type-arg]

    def test_resolves_phase_start(self) -> None:
        evt = self._ta.validate_python({
            "event": "phase_start", "batch_id": "b-1",
            "phase": 1, "phase_name": "Ingestion",
            "timestamp": datetime.now(UTC).isoformat(),
        })
        assert isinstance(evt, PhaseStartEvent)

    def test_resolves_step_progress(self) -> None:
        evt = self._ta.validate_python({
            "event": "step_progress", "batch_id": "b-1",
            "phase": 1, "step": "atomizer", "completed": 5, "total": 50,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        assert isinstance(evt, StepProgressEvent)

    def test_resolves_classification(self) -> None:
        evt = self._ta.validate_python({
            "event": "classification", "batch_id": "b-1",
            "atom_id": "a-1", "classification": "FIT", "confidence": 0.91,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        assert isinstance(evt, ClassificationEvent)

    def test_resolves_complete(self) -> None:
        evt = self._ta.validate_python({
            "event": "complete", "batch_id": "b-1",
            "total": 50, "fit_count": 36, "partial_fit_count": 7,
            "gap_count": 7, "review_count": 0,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        assert isinstance(evt, CompleteEvent)

    def test_resolves_error(self) -> None:
        evt = self._ta.validate_python({
            "event": "error", "batch_id": "b-1",
            "error_type": "ParseError", "message": "column not found",
            "timestamp": datetime.now(UTC).isoformat(),
        })
        assert isinstance(evt, ErrorEvent)

    def test_unknown_event_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._ta.validate_python({"event": "unknown_event", "batch_id": "b-1"})
