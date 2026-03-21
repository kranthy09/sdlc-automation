"""
G10-lite — Phase 5 sanity gate (Session G, Sub-phase 5A).

run_sanity_check(result, match, config) returns a list of flag-name strings.
A non-empty list means the result should be routed to the HITL review queue.

Three rules (from docs/specs/guardrails.md G10-lite):

  high_confidence_gap
      result.confidence > config.fit_confidence_threshold AND classification == GAP
      Why: high confidence implies strong retrieval evidence — a GAP verdict is suspicious
      when the composite score says the requirement is well-covered.

  low_score_fit
      match.top_composite_score < config.review_confidence_threshold AND classification == FIT
      Why: weak similarity from Phase 3 but LLM returned FIT — numbers don't support verdict.

  llm_schema_retry_exhausted
      result.route_used == RouteLabel.REVIEW_REQUIRED
      Why: LLM failed to produce valid structured output after max retries in Phase 4.

CRITICAL: never flip result.classification inside this function.
          Only accumulate flag strings. The human reviewer decides.
"""

from __future__ import annotations

from platform.observability.logger import get_logger
from platform.schemas.fitment import ClassificationResult, FitLabel, MatchResult, RouteLabel
from platform.schemas.product import ProductConfig

log = get_logger(__name__)


def run_sanity_check(
    result: ClassificationResult,
    match: MatchResult,
    config: ProductConfig,
) -> list[str]:
    """Return G10-lite flag names triggered by *result* / *match* pair.

    Args:
        result: Phase 4 ClassificationResult for a single requirement.
        match:  Phase 3 MatchResult for the same atom (provides composite score).
        config: ProductConfig carrying the thresholds (fit_confidence_threshold,
                review_confidence_threshold). Read from config — never hardcode.

    Returns:
        List of zero or more flag strings. Empty → result is sane, no HITL needed.
    """
    flags: list[str] = []

    # Rule 1 — high_confidence_gap
    if (
        result.classification == FitLabel.GAP
        and result.confidence > config.fit_confidence_threshold
    ):
        flags.append("high_confidence_gap")
        log.info(
            "sanity_high_confidence_gap",
            atom_id=result.atom_id,
            confidence=result.confidence,
            threshold=config.fit_confidence_threshold,
        )

    # Rule 2 — low_score_fit
    if (
        result.classification == FitLabel.FIT
        and match.top_composite_score < config.review_confidence_threshold
    ):
        flags.append("low_score_fit")
        log.info(
            "sanity_low_score_fit",
            atom_id=result.atom_id,
            composite=match.top_composite_score,
            threshold=config.review_confidence_threshold,
        )

    # Rule 3 — llm_schema_retry_exhausted
    if result.route_used == RouteLabel.REVIEW_REQUIRED:
        flags.append("llm_schema_retry_exhausted")
        log.info(
            "sanity_llm_schema_retry_exhausted",
            atom_id=result.atom_id,
        )

    return flags
