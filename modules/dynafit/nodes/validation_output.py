"""Phase 5 output assembly — CSV writing, override merging, batch building.

Pure data transformation helpers extracted from phase5_validation.py.
No infrastructure dependencies.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from typing import Any

from platform.schemas.fitment import (
    ClassificationResult,
    FitLabel,
    ValidatedFitmentBatch,
)

from ..state import DynafitState

# ---------------------------------------------------------------------------
# CSV column definition (FDD FOR FITS / FDD FOR GAPS)
# ---------------------------------------------------------------------------

_CSV_FIELDNAMES = [
    "req_id",
    "requirement",
    "module",
    "country",
    "wave",
    "classification",
    "confidence",
    "d365_capability",
    "rationale",
    "config_steps",
    "gap_description",
    "reviewer",
    "override",
]


# ---------------------------------------------------------------------------
# Internal DTO — carries override metadata alongside the resolved result
# ---------------------------------------------------------------------------


@dataclass
class _MergedResult:
    result: ClassificationResult
    reviewer_override: bool = False
    consultant: str | None = None


# ---------------------------------------------------------------------------
# Pure data helpers
# ---------------------------------------------------------------------------


def _merge_overrides(
    clean: list[ClassificationResult],
    flagged: list[tuple[ClassificationResult, list[str]]],
    overrides: dict[str, Any],
) -> list[_MergedResult]:
    """Merge human reviewer decisions into the flagged classification results.

    Args:
        clean:     Results that passed all sanity checks — no review needed.
        flagged:   (result, flags) pairs that were sent to the HITL queue.
        overrides: Map of atom_id → human decision.
                   None value (or missing key) → human approved original.
                   Dict value → human override with new classification + rationale.

    Returns:
        Merged list of _MergedResult, preserving the original ordering of
        clean results first, then resolved flagged results.
    """
    merged: list[_MergedResult] = [_MergedResult(result=r) for r in clean]

    for original, _flags in flagged:
        decision = overrides.get(original.atom_id)

        if decision and isinstance(decision, dict) and decision.get("classification"):
            new_classification = FitLabel(decision["classification"])
            consultant = decision.get("consultant")
            merged.append(
                _MergedResult(
                    result=original.model_copy(
                        update={
                            "classification": new_classification,
                            "rationale": decision.get("rationale", original.rationale),
                        }
                    ),
                    reviewer_override=True,
                    consultant=consultant,
                )
            )
        else:
            # Human approved the original classification — no change
            merged.append(_MergedResult(result=original))

    return merged


def _build_batch(
    state: DynafitState,
    merged: list[_MergedResult],
) -> ValidatedFitmentBatch:
    """Assemble ValidatedFitmentBatch from merged results.

    flagged_for_review is always empty here — all flagged items were resolved
    by the HITL reviewer before this function is called.
    """
    upload = state["upload"]
    results = [mr.result for mr in merged]
    counts: Counter[FitLabel] = Counter(r.classification for r in results)

    return ValidatedFitmentBatch(
        batch_id=state["batch_id"],
        upload_id=upload.upload_id,
        product_id=upload.product_id,
        wave=upload.wave,
        results=results,
        flagged_for_review=[],
        total_atoms=len(results),
        fit_count=counts.get(FitLabel.FIT, 0),
        partial_fit_count=counts.get(FitLabel.PARTIAL_FIT, 0),
        gap_count=counts.get(FitLabel.GAP, 0),
        review_count=counts.get(FitLabel.REVIEW_REQUIRED, 0),
    )


def _write_fdd_csv(
    path: str,
    results: list[_MergedResult],
) -> None:
    """Write a single FDD CSV file for the given results."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        for mr in results:
            r = mr.result
            writer.writerow(
                {
                    "req_id": r.atom_id,
                    "requirement": r.requirement_text,
                    "module": r.module,
                    "country": r.country,
                    "wave": r.wave,
                    "classification": str(r.classification),
                    "confidence": f"{r.confidence:.4f}",
                    "d365_capability": r.d365_capability_ref or "",
                    "rationale": r.rationale,
                    "config_steps": r.config_steps or "",
                    "gap_description": r.gap_description or "",
                    "reviewer": mr.consultant or "",
                    "override": "yes" if mr.reviewer_override else "",
                }
            )
