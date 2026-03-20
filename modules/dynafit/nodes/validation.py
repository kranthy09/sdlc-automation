"""
Validation node — Phase 5 of the DYNAFIT pipeline (Session G).

Responsibility: list[ClassificationResult] → ValidatedFitmentBatch

Steps (Session G):
  1. G10-lite sanity gate (modules/dynafit/guardrails.py):
       - high_confidence_gap: confidence > 0.85 AND classification == GAP
       - low_score_fit: composite_score < 0.60 AND classification == FIT
       - llm_schema_retry_exhausted: route_used == REVIEW_REQUIRED
  2. Country overrides: YAML rules per country (e.g. DE HGB/IFRS checks)
  3. Confidence filter: < 0.60 → forced HITL; anomaly flags → forced HITL
  4. HITL checkpoint via LangGraph interrupt():
       - Publish PhaseStartEvent(phase=5, phase_name="human_review") to Redis
       - interrupt({"batch_id": ..., "flagged_count": ...})
       - PostgreSQL checkpoint preserves full state
  5. Resume: merge consultant overrides → build ValidatedFitmentBatch
  6. Write-back: save each result + embedding to pgvector historical fitments
  7. Emit CompleteEvent to Redis
"""

from __future__ import annotations

from typing import Any

from platform.observability.logger import get_logger

from ..state import DynafitState

log = get_logger(__name__)


def validation_node(state: DynafitState) -> dict[str, Any]:
    """Phase 5 stub — sets validated_batch to None. Implemented in Session G.

    Note: the real implementation calls interrupt() for HITL when flagged items
    exist. This stub always completes so the smoke test can verify end-to-end
    graph execution.
    """
    log.debug("validation_stub", batch_id=state["batch_id"])
    return {
        "validated_batch": None,
    }
