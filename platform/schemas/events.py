"""
WebSocket progress event schemas.

These types are serialised by api/websocket/progress.py and consumed by the
React dashboard. The discriminated union on the ``event`` field lets clients
route each message to the correct handler without an explicit type registry.

Event lifecycle for a single batch:
  phase_start (×5)  → step_progress (many)  → classification (×N)
  → complete         or  error (at any point)

ProgressEvent is the union type used at the API boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from .base import PlatformModel
from .fitment import FitLabel

# ---------------------------------------------------------------------------
# Individual event types
# ---------------------------------------------------------------------------


class PhaseStartEvent(PlatformModel):
    """Emitted when the pipeline enters a new phase (1–5)."""

    event: Literal["phase_start"] = "phase_start"
    batch_id: str
    phase: Annotated[int, Field(ge=1, le=5)]
    phase_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StepProgressEvent(PlatformModel):
    """Emitted as atoms are processed within a phase step."""

    event: Literal["step_progress"] = "step_progress"
    batch_id: str
    phase: Annotated[int, Field(ge=1, le=5)]
    step: str
    completed: Annotated[int, Field(ge=0)]
    total: Annotated[int, Field(ge=1)]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ClassificationEvent(PlatformModel):
    """Emitted when Phase 4 classifies a single requirement.

    The optional fields (requirement_text, module, rationale, etc.) are
    populated during streaming so the consultant can inspect evidence
    immediately — not just after the full batch completes.
    """

    event: Literal["classification"] = "classification"
    batch_id: str
    atom_id: str
    classification: FitLabel
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    requirement_text: str = ""
    module: str = ""
    rationale: str = ""
    d365_capability: str = ""
    d365_navigation: str = ""
    journey: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PhaseCompleteEvent(PlatformModel):
    """Emitted when a pipeline phase finishes processing.

    Published by each phase node after it completes work, before the next
    phase starts. Carries per-phase atom counters and wall-clock latency so
    the UI can populate PhaseStatsCard without polling REST.
    """

    event: Literal["phase_complete"] = "phase_complete"
    batch_id: str
    phase: Annotated[int, Field(ge=1, le=5)]
    phase_name: str
    atoms_produced: Annotated[int, Field(ge=0)]
    atoms_validated: Annotated[int, Field(ge=0)]
    atoms_flagged: Annotated[int, Field(ge=0)]
    latency_ms: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CompleteEvent(PlatformModel):
    """Emitted when Phase 5 finishes and the report is ready."""

    event: Literal["complete"] = "complete"
    batch_id: str
    total: Annotated[int, Field(ge=0)]
    fit_count: Annotated[int, Field(ge=0)]
    partial_fit_count: Annotated[int, Field(ge=0)]
    gap_count: Annotated[int, Field(ge=0)]
    review_count: Annotated[int, Field(ge=0)]
    report_url: str | None = None
    results_url: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ErrorEvent(PlatformModel):
    """Emitted when an unrecoverable error occurs in any phase.

    phase and atom_id are optional — an error may be batch-level (no atom).
    error_type corresponds to the Python exception class name
    (e.g. 'ParseError', 'RetrievalError').
    """

    event: Literal["error"] = "error"
    batch_id: str
    phase: int | None = None
    atom_id: str | None = None
    error_type: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewRequiredEvent(PlatformModel):
    """Emitted when Phase 4 produces items that require human review (HITL).

    The pipeline pauses after this event until the reviewer resolves all items
    via POST /review/{batch_id}/complete.
    """

    event: Literal["review_required"] = "review_required"
    batch_id: str
    review_items: Annotated[int, Field(ge=0)]
    reasons: dict[str, int]
    review_url: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Discriminated union — used at the WebSocket boundary
# ---------------------------------------------------------------------------

type ProgressEvent = Annotated[
    PhaseStartEvent
    | StepProgressEvent
    | ClassificationEvent
    | PhaseCompleteEvent
    | CompleteEvent
    | ErrorEvent
    | ReviewRequiredEvent,
    Field(discriminator="event"),
]
