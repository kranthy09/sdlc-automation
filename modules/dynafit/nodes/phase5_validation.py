"""
Validation node — Phase 5 of the REQFIT pipeline (Session G).

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
  - ValidationNode.__call__ is synchronous; _write_back uses run_async.
  - Module-level singleton + validation_node() mirrors classification.py pattern.
  - Override dict keyed by atom_id; None value = human approved (keep original).
  - Write-back errors are logged as WARNING but do not fail the pipeline.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from langgraph.types import interrupt

from platform.config.settings import get_settings
from platform.observability.logger import get_logger
from platform.retrieval.embedder import Embedder
from platform.schemas.events import CompleteEvent
from platform.schemas.fitment import (
    ClassificationResult,
    FitLabel,
    MatchResult,
)
from platform.schemas.product import ProductConfig
from platform.storage.postgres import PostgresError, PostgresStore
from platform.storage.redis_pub import RedisPubSub

from ..events import (
    publish_phase_complete,
    publish_phase_start,
    run_async,
)
from ..guardrails import run_sanity_check
from ..product_config import get_product_config
from ..state import DynafitState
from .validation_output import (
    _build_batch,
    _merge_overrides,
    _MergedResult,
    _write_fdd_csv,
)

log = get_logger(__name__)


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

    def _get_embedder(self, product_id: str) -> Embedder:
        if self._embedder is None:
            config = get_product_config(product_id)
            self._embedder = Embedder(config.embedding_model)
        return self._embedder

    def _get_config(
        self, product_id: str, overrides: dict[str, Any] | None = None
    ) -> ProductConfig:
        base = (
            self._config_override
            if self._config_override is not None
            else get_product_config(product_id)
        )
        if overrides:
            recognized = {k: v for k, v in overrides.items()
                          if hasattr(base, k)}
            if recognized:
                return base.model_copy(update=recognized)
        return base

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
        classifications: list[ClassificationResult] = state.get(
            "classifications", [])
        match_results: list[MatchResult] = state.get("match_results", [])
        batch_id = state["batch_id"]
        config = self._get_config(
            state["upload"].product_id, state.get("config_overrides"))

        t0 = time.monotonic()
        log.info(
            "phase_start",
            phase=5,
            batch_id=batch_id,
            input_hash=hashlib.sha256(
                repr(classifications).encode()).hexdigest()[:16],
        )

        match_by_atom: dict[str, MatchResult] = {
            mr.atom.atom_id: mr for mr in match_results}

        # ----------------------------------------------------------------
        # Pass 1 (Sub-phase 5A): Sanity gate + confidence filter
        # ----------------------------------------------------------------
        flagged: list[tuple[ClassificationResult, list[str]]] = []
        clean: list[ClassificationResult] = []

        for result in classifications:
            flags = self._check_flags(
                result, match_by_atom.get(result.atom_id), config)
            if flags:
                flagged.append((result, flags))
            else:
                clean.append(result)

        # ----------------------------------------------------------------
        # HITL: interrupt if any items need human review
        # ----------------------------------------------------------------
        overrides: dict[str, Any] = {}
        if flagged:
            publish_phase_start(
                batch_id,
                phase=5,
                phase_name="human_review",
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
                    "flagged_reasons": {r.atom_id: flags for r, flags in flagged},
                }
            )
            overrides = raw if isinstance(raw, dict) else {}

        # ----------------------------------------------------------------
        # Pass 2 (Sub-phase 5B): Merge → build → write-back → report
        # ----------------------------------------------------------------
        merged = _merge_overrides(clean, flagged, overrides)
        batch = _build_batch(state, merged)
        pii_map = state.get("pii_redaction_map")
        report_path = self._write_csv(merged, batch.batch_id, pii_map)
        final_batch = batch.model_copy(update={"report_path": report_path})

        # Write-back to postgres (fire-and-forget; errors logged, not raised)
        run_async(self._write_back(merged, state))

        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "phase_complete",
            phase=5,
            batch_id=batch_id,
            output_hash=hashlib.sha256(
                repr(final_batch).encode()).hexdigest()[:16],
            guardrails_triggered=list({f for _, fs in flagged for f in fs}),
            latency_ms=round(elapsed_ms, 1),
        )

        # PhaseCompleteEvent MUST be published before CompleteEvent —
        # CompleteEvent is terminal and stops the Redis subscriber.
        publish_phase_complete(
            batch_id,
            phase=5,
            phase_name="Validation",
            atoms_produced=final_batch.total_atoms,
            atoms_validated=final_batch.total_atoms - final_batch.review_count,
            atoms_flagged=len(flagged),
            latency_ms=round(elapsed_ms, 1),
        )
        run_async(
            self._get_redis().publish(
                CompleteEvent(
                    batch_id=batch_id,
                    total=final_batch.total_atoms,
                    fit_count=final_batch.fit_count,
                    partial_fit_count=final_batch.partial_fit_count,
                    gap_count=final_batch.gap_count,
                    review_count=final_batch.review_count,
                    report_url=report_path,
                    results_url=f"/results/{batch_id}",
                )
            )
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
        elif result.classification == FitLabel.REVIEW_REQUIRED:
            # No MatchResult but LLM still failed to produce a valid label —
            # Rule 3 (llm_schema_retry_exhausted) must fire unconditionally.
            flags.append("llm_schema_retry_exhausted")

        # Confidence filter — non-GAP, non-REVIEW_REQUIRED results below threshold
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

        # Phase 3 anomaly flags → HITL
        if mr is not None and mr.anomaly_flags:
            flags.append("phase3_anomaly")
            log.info(
                "sanity_phase3_anomaly",
                atom_id=result.atom_id,
                anomalies=mr.anomaly_flags,
            )

        # G11: PII detected in LLM response → HITL (consultant must review)
        if result.caveats and "G11:" in result.caveats:
            flags.append("response_pii_leak")
            log.warning(
                "sanity_response_pii_leak",
                atom_id=result.atom_id,
            )

        return flags

    # ------------------------------------------------------------------
    # Sub-phase 5B helpers
    # ------------------------------------------------------------------

    def _write_csv(
        self,
        merged: list[_MergedResult],
        batch_id: str,
        pii_redaction_map: dict[str, str] | None = None,
    ) -> str:
        """Write FDD FOR FITS and FDD FOR GAPS CSVs.

        Returns the report directory path (stored as batch.report_path).
        The directory contains two CSVs:
          fdd_fits_{batch_id}.csv  — FIT and PARTIAL_FIT results
          fdd_gaps_{batch_id}.csv  — GAP results
        """
        report_dir = os.path.join(self._report_dir, batch_id)
        os.makedirs(report_dir, exist_ok=True)

        fits = [
            mr for mr in merged if mr.result.classification in (FitLabel.FIT, FitLabel.PARTIAL_FIT)
        ]
        gaps = [mr for mr in merged if mr.result.classification == FitLabel.GAP]

        fits_path = os.path.join(report_dir, f"fdd_fits_{batch_id}.csv")
        gaps_path = os.path.join(report_dir, f"fdd_gaps_{batch_id}.csv")
        _write_fdd_csv(fits_path, fits, pii_redaction_map)
        _write_fdd_csv(gaps_path, gaps, pii_redaction_map)

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

        All eligible requirement texts are embedded in a single embed_batch() call
        instead of one embed() call per result, reducing ONNX inference overhead
        from O(N) model invocations to a single batched pass.

        PostgresError per result is caught and logged as WARNING. Write-back
        failure does not fail the pipeline; the batch is already built in memory.
        """
        upload = state["upload"]
        embedder = self._get_embedder(upload.product_id)

        # Use injected instance (tests) or create fresh per invocation (prod).
        # Never cache in production: the module-level singleton is reused across
        # asyncio.run() calls (Celery retries), but asyncpg pools are bound to
        # the event loop in which they were created.
        pg = self._postgres
        owns_pg = pg is None
        if owns_pg:
            pg = PostgresStore(get_settings().postgres_url)

        # Partition: skip REVIEW_REQUIRED up-front
        eligible = [mr for mr in merged if mr.result.classification !=
                    FitLabel.REVIEW_REQUIRED]
        skipped = len(merged) - len(eligible)

        try:
            if not eligible:
                log.info(
                    "write_back_complete",
                    batch_id=state["batch_id"],
                    saved=0,
                    skipped_review_required=skipped,
                )
                return

            # One embed_batch call for all eligible texts
            texts = [mr.result.requirement_text for mr in eligible]
            embeddings: list[list[float]] = embedder.embed_batch(texts)

            saved = 0
            for mr, embedding in zip(eligible, embeddings, strict=True):
                try:
                    await pg.save_fitment(
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
        finally:
            if owns_pg:
                await pg.dispose()


# ---------------------------------------------------------------------------
# Module-level singleton + LangGraph entry point
# ---------------------------------------------------------------------------

_node: ValidationNode | None = None
_node_lock = __import__("threading").Lock()


def validation_node(state: DynafitState) -> dict[str, Any]:
    """LangGraph Phase 5 node — delegates to the cached ValidationNode.

    Tests should instantiate ValidationNode directly with mock dependencies
    instead of calling this function.
    """
    global _node
    if _node is None:
        with _node_lock:
            if _node is None:
                _node = ValidationNode()
    return _node(state)
