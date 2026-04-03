"""
Phase 5 Sanity Gate — G10-lite + Phase 5 Validation Checks.

run_sanity_check(result, match, config) returns a list of flag-name strings.
A non-empty list means the result should be routed to the HITL review queue.

Eight rules total:

G10-lite (from docs/specs/guardrails.md):
  1. high_confidence_gap
      result.confidence > config.fit_confidence_threshold AND classification == GAP
      Why: high confidence implies strong retrieval evidence — a GAP verdict is suspicious.

  2. low_score_fit
      match.top_composite_score < config.review_confidence_threshold AND classification == FIT
      Why: weak similarity from Phase 3 but LLM returned FIT — numbers don't support verdict.

  3. llm_schema_retry_exhausted
      result.classification == REVIEW_REQUIRED
      Why: LLM failed to produce valid structured output after max retries in Phase 4.

Phase 5 Validation (complementary checks):
  4. low_confidence
      result.classification not in (GAP, REVIEW_REQUIRED)
      AND result.confidence < config.review_confidence_threshold
      Why: catches results the LLM was uncertain about that G10-lite doesn't cover.

  5. gap_review
      result.classification == GAP
      Why: all GAP items require mandatory analyst sign-off (business rule).

  6. phase3_anomaly
      match.anomaly_flags is non-empty
      Why: Phase 3 flagged data quality issues; analyst must validate interpretation.

  7. response_pii_leak (G11 — PII guardrail)
      "G11:" in result.caveats
      Why: PII detected in LLM response — consultant must review before delivery.

  8. partial_fit_no_config
      result.classification == PARTIAL_FIT
      AND not result.configuration_steps AND not result.config_steps
      Why: LLM determined D365 requires configuration but could not specify steps —
           analyst must confirm and provide configuration guidance.

CRITICAL: never flip result.classification inside this function.
          Only accumulate flag strings. The human reviewer decides.
"""

from __future__ import annotations

from platform.observability.logger import get_logger
from platform.schemas.fitment import ClassificationResult, FitLabel, MatchResult
from platform.schemas.product import ProductConfig

log = get_logger(__name__)


def run_sanity_check(
    result: ClassificationResult,
    match: MatchResult | None,
    config: ProductConfig,
) -> list[str]:
    """Return sanity gate flags triggered by *result* / *match* pair.

    Checks both G10-lite rules (rules 1–3) and Phase 5 validation rules (rules 4–8).

    Args:
        result: Phase 4 ClassificationResult for a single requirement.
        match:  Phase 3 MatchResult for the same atom (optional; required for rules 1–2).
                If None, rules 1–2 are skipped; rules 3–8 still run.
        config: ProductConfig carrying thresholds (fit_confidence_threshold,
                review_confidence_threshold). Read from config — never hardcode.

    Returns:
        List of zero or more flag strings. Empty → result is sane, no HITL needed.
    """
    flags: list[str] = []

    # ========================================================================
    # G10-lite Rules (from docs/specs/guardrails.md)
    # ========================================================================

    # Rule 1 — high_confidence_gap
    if match is not None and (
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
    if match is not None and (
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
    if result.classification == FitLabel.REVIEW_REQUIRED:
        flags.append("llm_schema_retry_exhausted")
        log.info(
            "sanity_llm_schema_retry_exhausted",
            atom_id=result.atom_id,
        )

    # ========================================================================
    # Phase 5 Validation Rules (complementary to G10-lite)
    # ========================================================================

    # Rule 4 — low_confidence
    # Non-GAP, non-REVIEW_REQUIRED result below review confidence threshold.
    # Catches results the LLM was uncertain about that G10-lite doesn't cover.
    if (
        result.classification not in (
            FitLabel.GAP, FitLabel.REVIEW_REQUIRED)
        and result.confidence < config.review_confidence_threshold
    ):
        flags.append("low_confidence")
        log.info(
            "sanity_low_confidence",
            atom_id=result.atom_id,
            confidence=result.confidence,
            threshold=config.review_confidence_threshold,
        )

    # Rule 5 — gap_review
    # All GAP items require mandatory analyst sign-off (business rule).
    if result.classification == FitLabel.GAP:
        flags.append("gap_review")
        log.info("sanity_gap_mandatory_review", atom_id=result.atom_id)

    # Rule 6 — phase3_anomaly
    # Phase 3 flagged data quality issues; analyst must validate interpretation.
    if match is not None and match.anomaly_flags:
        flags.append("phase3_anomaly")
        log.info(
            "sanity_phase3_anomaly",
            atom_id=result.atom_id,
            anomalies=match.anomaly_flags,
        )

    # Rule 7 — response_pii_leak (G11 — PII guardrail)
    # PII detected in LLM response; consultant must review before delivery.
    if result.caveats and "G11:" in result.caveats:
        flags.append("response_pii_leak")
        log.warning(
            "sanity_response_pii_leak",
            atom_id=result.atom_id,
        )

    # Rule 8 — partial_fit_no_config
    # PARTIAL_FIT without configuration steps: LLM determined D365 requires
    # configuration but could not specify steps. Analyst must confirm and provide
    # or verify the required configuration guidance.
    if (
        result.classification == FitLabel.PARTIAL_FIT
        and not result.configuration_steps
        and not result.config_steps
    ):
        flags.append("partial_fit_no_config")
        log.info(
            "sanity_partial_fit_no_config",
            atom_id=result.atom_id,
        )

    return flags
