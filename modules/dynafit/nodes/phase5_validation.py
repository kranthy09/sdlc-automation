"""
Validation node — Phase 5 of the DYNAFIT pipeline (Session G).

Responsibility: list[ClassificationResult] → ValidatedFitmentBatch

Two logical passes within one node invocation, separated by LangGraph interrupt():

Pass 1 — Sanity Gate + HITL (Sub-phase 5A):
  1. G10-lite run_sanity_check() per atom (high_confidence_gap, low_score_fit,
     llm_schema_retry_exhausted) — from modules/dynafit/guardrails.py
  2. Confidence filter: confidence < review_confidence_threshold on non-GAP → forced HITL
  3. Phase 3 anomaly flags present → forced HITL
  4. If flagged items exist:
       publish PhaseStartEvent(phase=5, phase_name="human_review") → Redis
       interrupt({"batch_id": ..., "flagged_count": ..., "flagged_atom_ids": [...]})
       ← graph freezes; PostgreSQL checkpoint preserves full state
       ← API layer (Layer 4) handles reviewer interactions
       overrides = <resumed with human decisions>
  5. If no flagged items: skip interrupt, proceed directly to Pass 2

Pass 2 — Merge + Build + Write-back + Report (Sub-phase 5B):
  1. _merge_overrides(): apply human decisions to flagged results
  2. _build_batch(): assemble ValidatedFitmentBatch with correct counts
  3. _write_csv(): FDD FOR FITS + FDD FOR GAPS CSVs (stdlib csv, no new libs)
  4. _write_back(): save_fitment to postgres with embedding per finalized result
     (REVIEW_REQUIRED results are skipped — not final, postgres contract rejects them)
  5. Publish CompleteEvent → Redis

Design:
  - ValidationNode accepts injectable postgres / redis / embedder for tests.
  - Async bridge (_run_async) mirrors retrieval.py pattern — graph.invoke() stays sync.
  - Module-level singleton + validation_node() mirrors classification.py pattern.
  - Override dict keyed by atom_id; None value = human approved (keep original).
  - Write-back errors are logged as WARNING but do not fail the pipeline.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import interrupt

from platform.config.settings import get_settings
from platform.observability.logger import get_logger
from platform.retrieval.embedder import Embedder
from platform.schemas.events import CompleteEvent, PhaseStartEvent
from platform.schemas.fitment import (
    ClassificationResult,
    FitLabel,
    MatchResult,
    RouteLabel,
    ValidatedFitmentBatch,
)
from platform.schemas.product import ProductConfig
from platform.storage.postgres import PostgresError, PostgresStore
from platform.storage.redis_pub import RedisPubSub

from ..guardrails import run_sanity_check
from ..state import DynafitState

log = get_logger(__name__)

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
# ProductConfig MVP singleton (mirrors Phase 4 pattern)
# ---------------------------------------------------------------------------

_D365_FO_CONFIG: ProductConfig = ProductConfig(
    product_id="d365_fo",
    display_name="Dynamics 365 Finance & Operations",
    llm_model="claude-sonnet-4-6",
    embedding_model="BAAI/bge-large-en-v1.5",
    capability_kb_namespace="d365_fo_capabilities",
    doc_corpus_namespace="d365_fo_docs",
    historical_fitments_table="d365_fo_fitments",
    fit_confidence_threshold=0.85,
    review_confidence_threshold=0.60,
    auto_approve_with_history=True,
    country_rules_path="knowledge_bases/d365_fo/country_rules/",
    fdd_template_path="knowledge_bases/d365_fo/fdd_templates/fit_template.j2",
    code_language="xpp",
)


def _get_product_config(product_id: str) -> ProductConfig:
    if product_id == "d365_fo":
        return _D365_FO_CONFIG
    return _D365_FO_CONFIG.model_copy(update={"product_id": product_id})


# ---------------------------------------------------------------------------
# Async bridge (same pattern as retrieval.py)
# ---------------------------------------------------------------------------


def _run_async(coro: Any) -> Any:
    """Run a coroutine from a synchronous context.

    Uses asyncio.run() when there is no running event loop; falls back to a
    thread pool executor when a loop is already running (e.g. inside pytest-asyncio
    or an ASGI server thread).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Internal DTO — carries override metadata alongside the resolved result
# ---------------------------------------------------------------------------


@dataclass
class _MergedResult:
    result: ClassificationResult
    reviewer_override: bool = False
    consultant: str | None = None


# ---------------------------------------------------------------------------
# Pure data helpers (module-level, no infra dependencies)
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


# ---------------------------------------------------------------------------
# ValidationNode
# ---------------------------------------------------------------------------


class ValidationNode:
    """Phase 5 validation pipeline with injectable dependencies.

    In tests, inject mock infrastructure directly:

        node = ValidationNode(
            postgres=make_postgres_store(),
            redis=make_redis_pub_sub(),
            embedder=make_embedder(),
        )
        result = node(state)

    Production uses the module-level ``validation_node`` singleton which
    lazily initialises all dependencies from settings.

    Args:
        postgres:       PostgresStore for write-back. Lazily initialised if None.
        redis:          RedisPubSub for events. Lazily initialised if None.
        embedder:       Embedder for pgvector write-back embeddings. Lazily init if None.
        product_config: Override ProductConfig (useful in tests to fix thresholds).
        report_dir:     Directory prefix for FDD CSV output. Default: "reports".
    """

    def __init__(
        self,
        *,
        postgres: PostgresStore | None = None,
        redis: RedisPubSub | None = None,
        embedder: Embedder | None = None,
        product_config: ProductConfig | None = None,
        report_dir: str = "reports",
    ) -> None:
        self._postgres = postgres
        self._redis = redis
        self._embedder = embedder
        self._config_override = product_config
        self._report_dir = report_dir

    def _get_postgres(self) -> PostgresStore:
        if self._postgres is None:
            self._postgres = PostgresStore(get_settings().postgres_url)
        return self._postgres

    def _get_redis(self) -> RedisPubSub:
        if self._redis is None:
            self._redis = RedisPubSub(get_settings().redis_url)
        return self._redis

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder(get_settings().embedding_model)
        return self._embedder

    def _get_config(self, product_id: str) -> ProductConfig:
        if self._config_override is not None:
            return self._config_override
        return _get_product_config(product_id)

    # ------------------------------------------------------------------
    # LangGraph entry point
    # ------------------------------------------------------------------

    def __call__(self, state: DynafitState) -> dict[str, Any]:
        """Phase 5 node — sanity gate, HITL checkpoint, output builder.

        This function is called twice per HITL batch:
          1. First invocation: builds flagged queue, calls interrupt() if needed.
          2. After interrupt() resume: interrupt() returns overrides, execution
             continues from the line after interrupt() in the same call frame.
        """
        classifications: list[ClassificationResult] = state.get(  # type: ignore[assignment]
            "classifications", []
        )
        match_results: list[MatchResult] = state.get("match_results", [])  # type: ignore[assignment]
        batch_id = state["batch_id"]
        config = self._get_config(state["upload"].product_id)

        t0 = time.monotonic()
        log.info(
            "phase_start",
            phase=5,
            batch_id=batch_id,
            input_hash=hashlib.sha256(repr(classifications).encode()).hexdigest()[:16],
        )

        match_by_atom: dict[str, MatchResult] = {
            mr.atom.atom_id: mr for mr in match_results
        }

        # ----------------------------------------------------------------
        # Pass 1 (Sub-phase 5A): Sanity gate + confidence filter
        # ----------------------------------------------------------------
        flagged: list[tuple[ClassificationResult, list[str]]] = []
        clean: list[ClassificationResult] = []

        for result in classifications:
            flags = self._check_flags(result, match_by_atom.get(result.atom_id), config)
            if flags:
                flagged.append((result, flags))
            else:
                clean.append(result)

        # ----------------------------------------------------------------
        # HITL: interrupt if any items need human review
        # ----------------------------------------------------------------
        overrides: dict[str, Any] = {}
        if flagged:
            _run_async(
                self._get_redis().publish(
                    PhaseStartEvent(
                        batch_id=batch_id,
                        phase=5,
                        phase_name="human_review",
                    )
                )
            )
            log.info(
                "hitl_checkpoint",
                batch_id=batch_id,
                flagged_count=len(flagged),
                flagged_atom_ids=[r.atom_id for r, _ in flagged],
            )
            # LangGraph freezes here. PostgreSQL checkpoint preserves full state.
            # The API layer (Layer 4) serves GET/POST /batches/{id}/review endpoints.
            # graph.invoke(Command(resume=overrides), ...) resumes execution here.
            raw = interrupt(
                {
                    "batch_id": batch_id,
                    "flagged_count": len(flagged),
                    "flagged_atom_ids": [r.atom_id for r, _ in flagged],
                }
            )
            overrides = raw if isinstance(raw, dict) else {}

        # ----------------------------------------------------------------
        # Pass 2 (Sub-phase 5B): Merge → build → write-back → report
        # ----------------------------------------------------------------
        merged = _merge_overrides(clean, flagged, overrides)
        batch = _build_batch(state, merged)
        report_path = self._write_csv(merged, batch.batch_id)
        final_batch = batch.model_copy(update={"report_path": report_path})

        # Write-back to postgres (fire-and-forget; errors logged, not raised)
        _run_async(self._write_back(merged, state))

        _run_async(
            self._get_redis().publish(
                CompleteEvent(
                    batch_id=batch_id,
                    total=final_batch.total_atoms,
                    fit_count=final_batch.fit_count,
                    partial_fit_count=final_batch.partial_fit_count,
                    gap_count=final_batch.gap_count,
                    review_count=final_batch.review_count,
                    report_url=report_path,
                )
            )
        )

        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "phase_complete",
            phase=5,
            batch_id=batch_id,
            output_hash=hashlib.sha256(repr(final_batch).encode()).hexdigest()[:16],
            guardrails_triggered=list({f for _, fs in flagged for f in fs}),
            latency_ms=round(elapsed_ms, 1),
        )

        return {"validated_batch": final_batch}

    # ------------------------------------------------------------------
    # Sub-phase 5A helpers
    # ------------------------------------------------------------------

    def _check_flags(
        self,
        result: ClassificationResult,
        mr: MatchResult | None,
        config: ProductConfig,
    ) -> list[str]:
        """Return all flags for one result: G10-lite + confidence filter + anomaly.

        G10-lite rules (high_confidence_gap, low_score_fit, llm_schema_retry_exhausted)
        are delegated to modules/dynafit/guardrails.py.

        Additional checks here:
          - low_confidence: non-GAP result with confidence below review threshold
            (catches results the LLM was uncertain about that G10-lite doesn't cover)
          - phase3_anomaly: Phase 3 raised anomaly_flags for this atom
        """
        flags: list[str] = []

        if mr is not None:
            flags.extend(run_sanity_check(result, mr, config))

        # Confidence filter — non-GAP, non-REVIEW_REQUIRED results below threshold
        if (
            result.classification not in (FitLabel.GAP, FitLabel.REVIEW_REQUIRED)
            and result.confidence < config.review_confidence_threshold
        ):
            flags.append("low_confidence")
            log.info(
                "sanity_low_confidence",
                atom_id=result.atom_id,
                confidence=result.confidence,
                threshold=config.review_confidence_threshold,
            )

        # Phase 3 anomaly flags → HITL
        if mr is not None and mr.anomaly_flags:
            flags.append("phase3_anomaly")
            log.info(
                "sanity_phase3_anomaly",
                atom_id=result.atom_id,
                anomalies=mr.anomaly_flags,
            )

        return flags

    # ------------------------------------------------------------------
    # Sub-phase 5B helpers
    # ------------------------------------------------------------------

    def _write_csv(self, merged: list[_MergedResult], batch_id: str) -> str:
        """Write FDD FOR FITS and FDD FOR GAPS CSVs.

        Returns the report directory path (stored as batch.report_path).
        """
        report_dir = os.path.join(self._report_dir, batch_id)
        os.makedirs(report_dir, exist_ok=True)

        fits = [
            mr for mr in merged
            if mr.result.classification in (FitLabel.FIT, FitLabel.PARTIAL_FIT)
        ]
        gaps = [
            mr for mr in merged
            if mr.result.classification == FitLabel.GAP
        ]

        _write_fdd_csv(os.path.join(report_dir, f"fdd_fits_{batch_id}.csv"), fits)
        _write_fdd_csv(os.path.join(report_dir, f"fdd_gaps_{batch_id}.csv"), gaps)

        log.info(
            "report_written",
            batch_id=batch_id,
            report_dir=report_dir,
            fits=len(fits),
            gaps=len(gaps),
        )
        return report_dir

    async def _write_back(
        self,
        merged: list[_MergedResult],
        state: DynafitState,
    ) -> None:
        """Persist finalized ClassificationResults to postgres with pgvector embeddings.

        REVIEW_REQUIRED results are skipped — they are not final decisions and
        postgres.save_fitment() rejects them by contract.

        PostgresError per result is caught and logged as WARNING. Write-back
        failure does not fail the pipeline; the batch is already built in memory.
        """
        upload = state["upload"]
        embedder = self._get_embedder()
        postgres = self._get_postgres()
        saved = skipped = 0

        for mr in merged:
            if mr.result.classification == FitLabel.REVIEW_REQUIRED:
                skipped += 1
                continue
            try:
                embedding: list[float] = embedder.embed(
                    mr.result.requirement_text
                ).tolist()
                await postgres.save_fitment(
                    mr.result,
                    embedding,
                    upload_id=upload.upload_id,
                    product_id=upload.product_id,
                    reviewer_override=mr.reviewer_override,
                    consultant=mr.consultant,
                )
                saved += 1
            except PostgresError as exc:
                log.warning(
                    "write_back_failed",
                    atom_id=mr.result.atom_id,
                    error=str(exc),
                )

        log.info(
            "write_back_complete",
            batch_id=state["batch_id"],
            saved=saved,
            skipped_review_required=skipped,
        )


# ---------------------------------------------------------------------------
# Module-level singleton + LangGraph entry point
# ---------------------------------------------------------------------------

_node: ValidationNode | None = None


def validation_node(state: DynafitState) -> dict[str, Any]:
    """LangGraph Phase 5 node — delegates to the cached ValidationNode.

    Tests should instantiate ValidationNode directly with mock dependencies
    instead of calling this function.
    """
    global _node
    if _node is None:
        _node = ValidationNode()
    return _node(state)
