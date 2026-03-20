"""
Classification node — Phase 4 of the DYNAFIT pipeline (Session F).

Responsibility: list[MatchResult] → list[ClassificationResult]

Steps (Session F):
  1. Short-circuit: zero capabilities → auto-GAP (no LLM call)
  2. G8 prompt firewall: Jinja2 autoescape + StrictUndefined + allowed-template
     whitelist
  3. LLM reasoning by route:
       FAST_TRACK   → 1 call, temperature=0.0
       DEEP_REASON  → 3 calls, temperature=0.3, majority vote
       GAP_CONFIRM  → 1 call, temperature=0.0
  4. G9 output schema: XML parse → regex fallback → Pydantic strict validation;
     on exhausted retries → classification=REVIEW_REQUIRED
  5. Sanity check: FIT with composite <0.50 → PARTIAL_FIT;
     GAP with composite >0.85 → FLAG
"""

from __future__ import annotations

from typing import Any

from platform.observability.logger import get_logger

from ..state import DynafitState

log = get_logger(__name__)


def classification_node(state: DynafitState) -> dict[str, Any]:
    """Phase 4 stub — returns empty classification list. Implemented in Session F."""
    log.debug("classification_stub", batch_id=state["batch_id"])
    return {
        "classifications": [],
    }
