"""
G11: Response PII Scanner — detect PII leaked or hallucinated in LLM output.

Called at Phase 4, after LLM response assembly, before returning classification.
Reuses the same presidio/regex detection engine as G2 (pii_redactor.py).

If PII is found in the response, action is FLAG_FOR_REVIEW — the atom is routed
to Phase 5 HITL review so the consultant can inspect the leak before the batch
completes. This guardrail never blocks — it flags.

Audit: emits structured log with entity types and counts (never the PII values).
"""

from __future__ import annotations

from platform.observability.logger import get_logger
from platform.schemas.guardrails import PIIScanResult

from . import pii_redactor as _redactor

__all__ = ["scan_response_pii"]

log = get_logger(__name__)


def scan_response_pii(text: str) -> PIIScanResult:
    """Scan LLM response text for PII entities.

    Args:
        text: LLM output text to scan (rationale, gap_description, config_steps).

    Returns:
        PIIScanResult with detected entities and action (PASS or FLAG_FOR_REVIEW).
    """
    if not text.strip():
        return PIIScanResult(
            has_pii=False,
            entities_found=[],
            entity_count=0,
            action="PASS",
        )

    _redactor._get_analyzer()
    entities = (
        _redactor._detect_with_presidio(text)
        if _redactor._presidio_available
        else _redactor._detect_with_regex(text)
    )

    has_pii = len(entities) > 0
    action = "FLAG_FOR_REVIEW" if has_pii else "PASS"

    if has_pii:
        log.warning(
            "response_pii_detected",
            entity_count=len(entities),
            entity_types=[e.entity_type for e in entities],
            action=action,
        )
    else:
        log.debug("response_pii_scan_clean", action="PASS")

    return PIIScanResult(
        has_pii=has_pii,
        entities_found=entities,
        entity_count=len(entities),
        action=action,
    )
