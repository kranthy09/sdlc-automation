"""
Fitment pipeline schemas — the data shapes for Phase 3 (Matching) and Phase 4 (Classification).

Pipeline:
  AssembledContext → MatchResult  (Phase 3: multi-signal scoring + routing)
  MatchResult      → ClassificationResult  (Phase 4: LLM reasoning)
  ClassificationResult[] → ValidatedFitmentBatch  (Phase 5: consistency + report)

FitLabel              — four possible classification outcomes
RouteLabel            — three LLM routing tiers (cost vs. accuracy trade-off)
MatchResult           — Phase 3 output: composite scores + routing decision
ClassificationResult  — Phase 4 output: verdict + rationale from LLM
ValidatedFitmentBatch — Phase 5 output: the final deliverable for a batch
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import PlatformModel
from .requirement import ValidatedAtom
from .retrieval import RankedCapability

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FitLabel(StrEnum):
    """Classification verdict for a single requirement against D365."""

    FIT = "FIT"  # Standard D365 covers this completely
    PARTIAL_FIT = "PARTIAL_FIT"  # D365 covers with configuration (no X++ code)
    GAP = "GAP"  # Requires custom X++ development
    REVIEW_REQUIRED = "REVIEW_REQUIRED"  # LLM confidence too low → human review


class RouteLabel(StrEnum):
    """LLM routing tier assigned by Phase 3 composite scorer.

    FAST_TRACK  — composite > 0.85 AND history present → 1 LLM call, temperature=0.0
    DEEP_REASON — composite 0.60–0.85 → 3 LLM calls + majority vote
    GAP_CONFIRM — composite < 0.60 → 1 LLM call confirming GAP
    """

    FAST_TRACK = "FAST_TRACK"
    DEEP_REASON = "DEEP_REASON"
    GAP_CONFIRM = "GAP_CONFIRM"


# ---------------------------------------------------------------------------
# MatchResult
# ---------------------------------------------------------------------------


class MatchResult(PlatformModel):
    """Phase 3 output: multi-signal composite scores and routing decision.

    composite_scores and ranked_capabilities must have the same length —
    each score corresponds to the capability at the same index.
    """

    atom: ValidatedAtom
    ranked_capabilities: list[RankedCapability]
    composite_scores: list[float]
    route: RouteLabel
    top_composite_score: Annotated[float, Field(ge=0.0, le=1.0)]
    anomaly_flags: list[str] = Field(default_factory=list)
    signal_breakdown: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def scores_align_with_capabilities(self) -> Self:
        if len(self.composite_scores) != len(self.ranked_capabilities):
            raise ValueError(
                f"composite_scores length ({len(self.composite_scores)}) must equal "
                f"ranked_capabilities length ({len(self.ranked_capabilities)})"
            )
        return self


# ---------------------------------------------------------------------------
# ClassificationResult
# ---------------------------------------------------------------------------


class ClassificationResult(PlatformModel):
    """Phase 4 output: LLM classification verdict for a single requirement."""

    atom_id: str
    requirement_text: str
    module: str
    country: str
    wave: Annotated[int, Field(ge=1)]

    classification: FitLabel
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    rationale: str

    # Capability reference from the evidence presented to the LLM
    d365_capability_ref: str | None = None

    # Populated when classification=PARTIAL_FIT
    config_steps: str | None = None

    # Populated when classification=GAP
    gap_description: str | None = None

    # Structured config actions for PARTIAL_FIT (from LLM tool-use)
    configuration_steps: list[str] | None = None

    # GAP t-shirt sizing and categorisation
    dev_effort: Literal["S", "M", "L"] | None = None
    gap_type: str | None = None

    # Country-specific caveats or uncertainty notes
    caveats: str | None = None

    route_used: RouteLabel
    llm_calls_used: Annotated[int, Field(ge=0)] = 1


# ---------------------------------------------------------------------------
# ValidatedFitmentBatch
# ---------------------------------------------------------------------------


class ValidatedFitmentBatch(PlatformModel):
    """Phase 5 output: the complete validated fitment batch for a wave.

    Invariant: fit_count + partial_fit_count + gap_count + review_count == total_atoms
    This is enforced at construction time so downstream consumers can trust the counts.
    """

    batch_id: str
    upload_id: str
    product_id: str
    wave: Annotated[int, Field(ge=1)]

    results: list[ClassificationResult]
    flagged_for_review: list[ClassificationResult] = Field(default_factory=list)

    # Counts (must sum to total_atoms)
    total_atoms: Annotated[int, Field(ge=0)]
    fit_count: Annotated[int, Field(ge=0)]
    partial_fit_count: Annotated[int, Field(ge=0)]
    gap_count: Annotated[int, Field(ge=0)]
    review_count: Annotated[int, Field(ge=0)]

    # Set after report is written
    report_path: str | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def counts_sum_to_total(self) -> Self:
        total = self.fit_count + self.partial_fit_count + self.gap_count + self.review_count
        if total != self.total_atoms:
            raise ValueError(
                f"fit_count + partial_fit_count + gap_count + review_count ({total}) "
                f"must equal total_atoms ({self.total_atoms})"
            )
        return self
