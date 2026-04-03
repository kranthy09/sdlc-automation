"""
DynafitState — LangGraph state accumulator for the REQFIT 5-phase pipeline.

The state TypedDict is the single data contract between all phase nodes.
Each node:
  - reads from state (treat it as immutable during the node's execution)
  - returns a partial dict that LangGraph merges back into state

Required at graph entry (provided by the API/worker layer):
  upload    — raw document bytes + upload metadata
  batch_id  — UUID identifying this pipeline run
  errors    — starts as [] (accumulates via operator.add reducer)

Phase output fields are NotRequired — they are absent until their phase runs:
  Phase 1 → atoms, validated_atoms, flagged_atoms
  Phase 2 → retrieval_contexts
  Phase 3 → match_results
  Phase 4 → classifications
  Phase 5 → validated_batch
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict

from platform.schemas.fitment import ClassificationResult, MatchResult, ValidatedFitmentBatch
from platform.schemas.requirement import FlaggedAtom, RawUpload, RequirementAtom, ValidatedAtom
from platform.schemas.retrieval import AssembledContext


class DynafitState(TypedDict):
    # --- Required inputs (provided at graph.invoke() call site) --------------
    upload: RawUpload  # raw document bytes + upload metadata
    batch_id: str  # UUID; also used as LangGraph thread_id for checkpointing

    # --- Cross-cutting (required; errors accumulate across all phases) --------
    errors: Annotated[list[str], operator.add]  # start as [] at entry

    # --- Phase 1 — Ingestion -------------------------------------------------
    # raw atoms after parse + atomize
    atoms: NotRequired[list[RequirementAtom]]
    validated_atoms: NotRequired[list[ValidatedAtom]]  # passed quality gates
    flagged_atoms: NotRequired[list[FlaggedAtom]]  # need human review

    # --- Phase 1 — Unified Multimodal Ingestion (Phases B–E) -----
    # enriched_chunks: serialized EnrichedChunk.model_dump() list
    #   — output from platform/ingestion/chunker.py (Phase E)
    #   — preferentially used by downstream phases for structured content
    # artifact_store_batch_path: path to batch artifact directory
    #   — e.g., "{DATA_DIR}/artifacts/{batch_id}"
    #   — used by Phase 5 HITL review and API artifact retrieval endpoints
    enriched_chunks: NotRequired[list[dict[str, Any]]]
    artifact_store_batch_path: NotRequired[str]

    # --- Phase 2 — Knowledge Retrieval (RAG) ---------------------------------
    # one per validated atom
    retrieval_contexts: NotRequired[list[AssembledContext]]

    # --- Phase 3 — Semantic Matching -----------------------------------------
    # composite scores + route tier
    match_results: NotRequired[list[MatchResult]]

    # --- Phase 4 — LLM Classification ----------------------------------------
    # FIT/PARTIAL_FIT/GAP
    classifications: NotRequired[list[ClassificationResult]]

    # --- Phase 5 — Validation + HITL -----------------------------------------
    # final deliverable
    validated_batch: NotRequired[ValidatedFitmentBatch | None]

    # --- Per-run ProductConfig overrides (from API config_overrides) ----------
    # Recognized keys: fit_confidence_threshold, review_confidence_threshold,
    # auto_approve_with_history. Phase 5 applies these via model_copy.
    config_overrides: NotRequired[dict[str, Any]]

    # --- PII redaction (G2 → Phase 1, restored in Phase 5 CSV output) ---------
    # placeholder → original text
    pii_redaction_map: NotRequired[dict[str, str]]
