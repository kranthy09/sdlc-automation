"""Presentation utilities — transform pipeline state into API-ready dicts.

This module owns all domain-aware data shaping that the API layer
(tasks.py, routes) needs. It reads internal schemas (ClassificationResult,
MatchResult, AssembledContext, ValidatedFitmentBatch) and produces plain
dicts suitable for JSON serialization and Redis storage.

The API layer calls these functions and writes the results — it never
inspects internal schema fields directly.
"""

from __future__ import annotations

from typing import Any


# Flag strings from Phase 5 _check_flags() that indicate a structural
# anomaly rather than simple low confidence.
_ANOMALY_FLAG_NAMES = frozenset(
    {
        "phase3_anomaly",
        "high_confidence_gap",
        "low_score_fit",
        "llm_schema_retry_exhausted",
    }
)


def review_reason(flags: list[str]) -> str:
    """Map a Phase 5 flag list to the UI review_reason discriminator."""
    if "response_pii_leak" in flags:
        return "pii_detected"
    if "gap_review" in flags:
        return "gap_review"
    if "partial_fit_no_config" in flags:
        return "partial_fit_no_config"
    if any(f in _ANOMALY_FLAG_NAMES for f in flags):
        return "anomaly"
    return "low_confidence"


def build_single_atom_journey(
    atom_id: str,
    atom: Any | None,
    ctx: Any | None,
    mr: Any | None,
    cls: Any | None,
    *,
    reviewer_override: bool = False,
) -> dict[str, Any] | None:
    """Build journey data for a single atom.

    This is the streaming counterpart to build_journey_data(). Called
    per-atom as classifications complete, so the consultant can drill
    into evidence immediately. Also used by build_journey_data() to
    eliminate duplication.

    Returns None if cls is missing (no classification result).
    """
    if not cls:
        return None

    ingest = {
        "atom_id": atom_id,
        "requirement_text": cls.requirement_text,
        "module": cls.module,
        "country": cls.country,
        "intent": atom.intent if atom else "FUNCTIONAL",
        "priority": atom.priority if atom else "SHOULD",
        "entity_hints": atom.entity_hints if atom else [],
        "specificity_score": (
            atom.specificity_score if atom else 0.0
        ),
        "completeness_score": (
            atom.completeness_score if atom else 0.0
        ),
        "content_type": atom.content_type if atom else "text",
        "source_refs": atom.source_refs if atom else [],
    }

    retrieve = {
        "capabilities": [
            {
                "name": cap.feature,
                "score": cap.composite_score,
                "navigation": cap.navigation,
            }
            for cap in (ctx.capabilities[:5] if ctx else [])
        ],
        "ms_learn_refs": [
            {"title": ref.title, "score": ref.score}
            for ref in (
                ctx.ms_learn_refs[:3] if ctx else []
            )
        ],
        "prior_fitments": [
            {
                "wave": pf.wave,
                "country": pf.country,
                "classification": pf.classification,
            }
            for pf in (ctx.prior_fitments if ctx else [])
        ],
        "retrieval_confidence": (
            ctx.retrieval_confidence if ctx else "LOW"
        ),
    }

    match = {
        "signal_breakdown": (
            mr.signal_breakdown if mr else {}
        ),
        "composite_score": (
            mr.top_composite_score if mr else 0.0
        ),
        "route": str(mr.route) if mr else "",
        "anomaly_flags": mr.anomaly_flags if mr else [],
    }

    d365_nav = (
        mr.ranked_capabilities[0].navigation
        if mr and mr.ranked_capabilities
        else ""
    )
    classify = {
        "classification": str(cls.classification),
        "confidence": cls.confidence,
        "rationale": cls.rationale,
        "route_used": str(cls.route_used),
        "llm_calls_used": cls.llm_calls_used,
        "d365_capability": cls.d365_capability_ref or "",
        "d365_navigation": d365_nav,
    }

    output = {
        "classification": str(cls.classification),
        "confidence": cls.confidence,
        "config_steps": cls.config_steps,
        "configuration_steps": cls.configuration_steps,
        "gap_description": cls.gap_description,
        "gap_type": cls.gap_type,
        "dev_effort": cls.dev_effort,
        "reviewer_override": reviewer_override,
    }

    return {
        "atom_id": atom_id,
        "ingest": ingest,
        "retrieve": retrieve,
        "match": match,
        "classify": classify,
        "output": output,
    }


def build_journey_data(
    final_state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Join Phase 1-5 data by atom_id into per-atom journey dicts."""
    validated_atoms = final_state.get("validated_atoms") or []
    contexts = final_state.get("retrieval_contexts") or []
    match_results = final_state.get("match_results") or []
    classifications = final_state.get("classifications") or []
    vb = final_state.get("validated_batch")

    atom_by_id = {a.atom_id: a for a in validated_atoms}
    ctx_by_id = {c.atom.atom_id: c for c in contexts}
    mr_by_id = {m.atom.atom_id: m for m in match_results}
    cls_by_id = {c.atom_id: c for c in classifications}

    reviewed_ids: set[str] = set()
    if vb:
        for r in vb.results:
            if (
                hasattr(r, "reviewer_override")
                and r.reviewer_override
            ):
                reviewed_ids.add(r.atom_id)

    journeys: list[dict[str, Any]] = []
    all_ids = list(cls_by_id.keys()) or list(atom_by_id.keys())

    for atom_id in all_ids:
        journey = build_single_atom_journey(
            atom_id=atom_id,
            atom=atom_by_id.get(atom_id),
            ctx=ctx_by_id.get(atom_id),
            mr=mr_by_id.get(atom_id),
            cls=cls_by_id.get(atom_id),
            reviewer_override=atom_id in reviewed_ids,
        )
        if journey:
            journeys.append(journey)

    return journeys


def build_complete_data(
    final_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Build result dicts, summary, and journey for a completed batch.

    Called by Celery worker (_finish_complete) when pipeline completes.
    Builds dicts that are:
      - Written to PostgreSQL: results (batch_results table), summary (batches table)
      - Cached in Redis: journey (transient, for /journey queries)

    The API layer reads the PostgreSQL results and builds typed responses.
    Journey is optional — if Redis is unavailable, /journey returns empty gracefully.

    Returns None if validated_batch is absent.
    Returns dict with keys: results, summary, journey, report_path, total_atoms.
    """
    vb = final_state.get("validated_batch")
    if not vb:
        return None

    match_by_atom = {
        mr.atom.atom_id: mr
        for mr in (final_state.get("match_results") or [])
    }
    context_by_atom = {
        ctx.atom.atom_id: ctx
        for ctx in (
            final_state.get("retrieval_contexts") or []
        )
    }

    result_dicts: list[dict[str, Any]] = []
    by_module: dict[str, dict[str, int]] = {}

    for r in vb.results:
        mr = match_by_atom.get(r.atom_id)
        ctx = context_by_atom.get(r.atom_id)

        evidence = {
            "top_capability_score": (
                mr.top_composite_score if mr else 0.0
            ),
            "retrieval_confidence": (
                ctx.retrieval_confidence if ctx else "LOW"
            ),
            "prior_fitments": [
                {
                    "wave": pf.wave,
                    "country": pf.country,
                    "classification": pf.classification,
                }
                for pf in (ctx.prior_fitments if ctx else [])
            ],
            "candidates": [
                {
                    "name": cap.feature,
                    "score": cap.composite_score,
                    "navigation": cap.navigation,
                }
                for cap in (mr.ranked_capabilities[:3] if mr else [])
            ],
            "route": str(mr.route) if mr else "",
            "anomaly_flags": mr.anomaly_flags if mr else [],
            "signal_breakdown": mr.signal_breakdown if mr else {},
        }

        d365_navigation = (
            mr.ranked_capabilities[0].navigation
            if mr and mr.ranked_capabilities
            else ""
        )

        result_dicts.append(
            {
                "atom_id": r.atom_id,
                "requirement_text": r.requirement_text,
                "classification": str(r.classification),
                "confidence": r.confidence,
                "module": r.module,
                "country": r.country,
                "wave": r.wave,
                "rationale": r.rationale,
                "reviewer_override": False,
                "d365_capability": (
                    r.d365_capability_ref or ""
                ),
                "d365_navigation": d365_navigation,
                "evidence": evidence,
                "config_steps": r.config_steps,
                "gap_description": r.gap_description,
                "configuration_steps": r.configuration_steps,
                "dev_effort": r.dev_effort,
                "gap_type": r.gap_type,
                "caveats": r.caveats,
                "route_used": str(r.route_used),
            }
        )

        cls = str(r.classification)
        if cls in ("FIT", "PARTIAL_FIT", "GAP"):
            mod = by_module.setdefault(
                r.module,
                {"fit": 0, "partial_fit": 0, "gap": 0},
            )
            if cls == "FIT":
                mod["fit"] += 1
            elif cls == "PARTIAL_FIT":
                mod["partial_fit"] += 1
            else:
                mod["gap"] += 1

    journey_data = build_journey_data(final_state)

    return {
        "results": result_dicts,
        "summary": {
            "total": vb.total_atoms,
            "fit": vb.fit_count,
            "partial_fit": vb.partial_fit_count,
            "gap": vb.gap_count,
            "by_module": by_module,
        },
        "journey": journey_data,
        "report_path": vb.report_path or "",
        "total_atoms": vb.total_atoms,
    }


def build_hitl_data(
    final_state: dict[str, Any],
    flagged_ids: set[str],
    flagged_reasons: dict[str, list[str]],
) -> dict[str, Any]:
    """Build review items, auto-approved items, summary, and journey for HITL pause.

    Called by Celery worker (_finish_hitl) during Phase 5 pause.
    Builds dicts that are:
      - Written to PostgreSQL: auto_approved results (batch_results table)
      - Cached in Redis: review_items, auto_approved, journey (transient)

    The API layer reads the PostgreSQL results and serves them via /results.
    Review items are read from PostgreSQL (review_items table) during /review queries.

    Returns dict with keys: review_items, auto_approved, summary,
    journey, reasons_counts, review_count.
    """
    classifications = (
        final_state.get("classifications") or []
    )
    review_needed = [
        c for c in classifications if c.atom_id in flagged_ids
    ]

    match_by_atom = {
        mr.atom.atom_id: mr
        for mr in (final_state.get("match_results") or [])
    }
    context_by_atom = {
        ctx.atom.atom_id: ctx
        for ctx in (
            final_state.get("retrieval_contexts") or []
        )
    }

    # Build review items for HITL queue (will be cached in Redis and persisted to PostgreSQL)
    review_item_dicts: list[dict[str, Any]] = []
    # Count reasons for review (anomaly, pii_detected, low_confidence)
    reasons_counts: dict[str, int] = {}
    for c in review_needed:
        mr = match_by_atom.get(c.atom_id)
        ctx = context_by_atom.get(c.atom_id)

        anomaly_flags = mr.anomaly_flags if mr else []
        item_flags = flagged_reasons.get(c.atom_id, [])
        reason = (
            review_reason(item_flags)
            if item_flags
            else (
                "anomaly"
                if anomaly_flags
                else "low_confidence"
            )
        )
        reasons_counts[reason] = (
            reasons_counts.get(reason, 0) + 1
        )

        # Build review item dict with evidence and classification detail
        review_item_dicts.append(
            {
                "atom_id": c.atom_id,
                "requirement_text": c.requirement_text,
                "ai_classification": str(c.classification),
                "ai_confidence": c.confidence,
                "ai_rationale": c.rationale,
                "review_reason": reason,
                "module": c.module,
                "config_steps": c.config_steps,
                "gap_description": c.gap_description,
                "configuration_steps": (
                    c.configuration_steps
                ),
                "dev_effort": c.dev_effort,
                "gap_type": c.gap_type,
                "evidence": {
                    "capabilities": [
                        {
                            "name": cap.feature,
                            "score": cap.composite_score,
                            "navigation": cap.navigation,
                        }
                        for cap in (
                            mr.ranked_capabilities[:3]
                            if mr
                            else []
                        )
                    ],
                    "prior_fitments": [
                        {
                            "wave": pf.wave,
                            "country": pf.country,
                            "classification": (
                                pf.classification
                            ),
                        }
                        for pf in (
                            ctx.prior_fitments
                            if ctx
                            else []
                        )
                    ],
                    "anomaly_flags": anomaly_flags,
                    "ms_learn_refs": [
                        {
                            "title": ref.title,
                            "score": ref.score,
                        }
                        for ref in (
                            ctx.ms_learn_refs[:3]
                            if ctx
                            else []
                        )
                    ],
                },
            }
        )
    # Build auto-approved results (atoms not flagged for review have final classifications)
    # These will be written to PostgreSQL batch_results table immediately
    auto_approved_dicts: list[dict[str, Any]] = []
    fit_count = partial_fit_count = gap_count = 0

    for c in classifications:
        cls = str(c.classification)
        if cls == "FIT":
            fit_count += 1
        elif cls == "PARTIAL_FIT":
            partial_fit_count += 1
        elif cls == "GAP":
            gap_count += 1

        if c.atom_id in flagged_ids:
            continue

        mr = match_by_atom.get(c.atom_id)
        ctx = context_by_atom.get(c.atom_id)
        d365_navigation = (
            mr.ranked_capabilities[0].navigation
            if mr and mr.ranked_capabilities
            else ""
        )
        # Build auto-approved result dict with full classification metadata and evidence
        auto_approved_dicts.append(
            {
                "atom_id": c.atom_id,
                "requirement_text": c.requirement_text,
                "classification": cls,
                "confidence": c.confidence,
                "module": c.module,
                "rationale": c.rationale,
                "d365_capability": (
                    c.d365_capability_ref or ""
                ),
                "d365_navigation": d365_navigation,
                "config_steps": c.config_steps,
                "configuration_steps": (
                    c.configuration_steps
                ),
                "gap_description": c.gap_description,
                "gap_type": c.gap_type,
                "dev_effort": c.dev_effort,
                "evidence": {
                    "capabilities": [
                        {
                            "name": cap.feature,
                            "score": cap.composite_score,
                            "navigation": cap.navigation,
                        }
                        for cap in (
                            mr.ranked_capabilities[:3]
                            if mr
                            else []
                        )
                    ],
                    "prior_fitments": [
                        {
                            "wave": pf.wave,
                            "country": pf.country,
                            "classification": (
                                pf.classification
                            ),
                        }
                        for pf in (
                            ctx.prior_fitments
                            if ctx
                            else []
                        )
                    ],
                    "anomaly_flags": [],
                    "ms_learn_refs": [
                        {
                            "title": ref.title,
                            "score": ref.score,
                        }
                        for ref in (
                            ctx.ms_learn_refs[:3]
                            if ctx
                            else []
                        )
                    ],
                },
            }
        )

    journey_data = build_journey_data(final_state)

    # Return dict with separate collections for review queue (Redis) and summary
    # API layer reads from PostgreSQL; this dict is for Celery worker caching only
    return {
        "review_items": review_item_dicts,
        "auto_approved": auto_approved_dicts,
        "summary": {
            "total": len(classifications),
            "fit": fit_count,
            "partial_fit": partial_fit_count,
            "gap": gap_count,
        },
        "journey": journey_data,
        "reasons_counts": reasons_counts,
        "review_count": len(review_needed),
    }
