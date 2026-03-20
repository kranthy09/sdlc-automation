"""
Matching node — Phase 3 of the DYNAFIT pipeline (Session E).

Responsibility: list[AssembledContext] → list[MatchResult]

Pipeline:
  1. Batch embed atom text + all capability descriptions (one embedder call per context)
  2. Compute 5 signals per (atom, capability) pair:
       embedding_cosine  (weight 0.25) — L2-normalised dot product
       entity_overlap    (weight 0.20) — atom entity_hints found in cap text
       token_ratio       (weight 0.15) — rapidfuzz token_set_ratio
       historical_alignment (weight 0.25) — 1.0 if prior fitments exist, else 0.0
       rerank_score      (weight 0.15) — cross-encoder score from Phase 2
  3. Weighted composite + optional FIT-prior history boost (+0.10, capped at 1.0)
  4. Anomaly detection: cosine > 0.85 but entity_overlap < 0.20 → FLAG
  5. Candidate ranker: sort descending, dedup by description cosine (> 0.95)
  6. Route assignment: FAST_TRACK | DEEP_REASON | GAP_CONFIRM

Design notes:
  - No LLM calls. All computation is local (numpy + rapidfuzz).
  - No direct infra imports — embedder injected via MatchingNode.__init__.
  - Pure helpers (_compute_composite, _assign_route, _detect_anomaly,
    _entity_overlap_score) are module-level so tests can exercise them directly.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from platform.observability.logger import get_logger
from platform.retrieval.embedder import Embedder
from platform.schemas.fitment import MatchResult, RouteLabel
from platform.schemas.retrieval import AssembledContext, PriorFitment, RankedCapability

from ..state import DynafitState

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Weights and thresholds  (spec §Phase 3 Step 2)
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, float] = {
    "embedding_cosine": 0.25,
    "entity_overlap": 0.20,
    "token_ratio": 0.15,
    "historical_alignment": 0.25,
    "rerank_score": 0.15,
}

_FAST_TRACK_THRESHOLD: float = 0.85   # composite > this AND history → FAST_TRACK
_GAP_CONFIRM_THRESHOLD: float = 0.60  # composite < this → GAP_CONFIRM

_ANOMALY_COSINE_MIN: float = 0.85     # above which entity absence is suspicious
_ANOMALY_ENTITY_MAX: float = 0.20     # below which anomaly is raised

_HISTORY_BOOST: float = 0.10          # added to composite when a FIT prior exists
_DEDUP_THRESHOLD: float = 0.95        # cosine above which two caps are duplicates


# ---------------------------------------------------------------------------
# Pure helpers — tested directly in tests/integration/test_phase3.py
# ---------------------------------------------------------------------------


def _compute_composite(signals: dict[str, float]) -> float:
    """Weighted linear combination of the 5 signals. Returns value in [0, 1]."""
    return min(1.0, sum(_WEIGHTS[k] * signals[k] for k in _WEIGHTS))


def _assign_route(composite: float, has_history: bool) -> RouteLabel:
    """Assign routing tier from composite score and history presence (spec §Phase 3 Step 2)."""
    if composite > _FAST_TRACK_THRESHOLD and has_history:
        return RouteLabel.FAST_TRACK
    if composite >= _GAP_CONFIRM_THRESHOLD:
        return RouteLabel.DEEP_REASON
    return RouteLabel.GAP_CONFIRM


def _detect_anomaly(embedding_cosine: float, entity_overlap: float) -> str | None:
    """Flag high semantic similarity without entity agreement (possible false positive).

    Example: "three-way handshake" vs "three-way matching" — cosine is high
    because of shared vocabulary but entity overlap would be near-zero.
    """
    if embedding_cosine > _ANOMALY_COSINE_MIN and entity_overlap < _ANOMALY_ENTITY_MAX:
        return (
            f"high_cosine_no_entity: cosine={embedding_cosine:.2f} "
            f"entity_overlap={entity_overlap:.2f}"
        )
    return None


def _entity_overlap_score(atom_hints: list[str], cap_text: str) -> float:
    """Fraction of atom entity hints that appear anywhere in the capability text.

    Uses atom.entity_hints (pre-computed by Phase 1 spaCy NER) as the reference
    set, then checks string-contains against the combined feature + description.
    Returns 0.0 if atom has no entity hints.
    """
    if not atom_hints:
        return 0.0
    cap_lower = cap_text.lower()
    found = sum(1 for hint in atom_hints if hint in cap_lower)
    return found / len(atom_hints)


def _token_ratio_score(text_a: str, text_b: str) -> float:
    """rapidfuzz token_set_ratio normalised to [0, 1]. Returns 0.0 if unavailable."""
    try:
        from rapidfuzz.fuzz import token_set_ratio  # noqa: PLC0415

        return token_set_ratio(text_a, text_b) / 100.0
    except ImportError:
        return 0.0


def _normalise(vecs: np.ndarray) -> np.ndarray:  # type: ignore[type-arg]
    """L2-normalise each row. Zero-norm rows are kept as-is (result is zero vector)."""
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vecs / norms


# ---------------------------------------------------------------------------
# MatchingNode
# ---------------------------------------------------------------------------


class MatchingNode:
    """Phase 3 semantic matching pipeline with injectable dependencies.

    Instantiate directly in tests with mock infrastructure:

        node = MatchingNode(embedder=make_embedder())
        result = node(state)

    Production code uses the module-level ``matching_node`` singleton which
    lazily initialises MatchingNode with the default bge-large embedder.

    Args:
        embedder: Sentence-transformer embedder for embedding cosine computation.
                  Lazily initialised with bge-large-en-v1.5 if not provided.
    """

    def __init__(self, *, embedder: Embedder | None = None) -> None:
        self._embedder = embedder

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder("BAAI/bge-large-en-v1.5")
        return self._embedder

    # ------------------------------------------------------------------
    # LangGraph entry point
    # ------------------------------------------------------------------

    def __call__(self, state: DynafitState) -> dict[str, Any]:
        contexts: list[AssembledContext] = state.get(  # type: ignore[assignment]
            "retrieval_contexts", []
        )
        if not contexts:
            log.debug("matching_skipped_no_contexts", batch_id=state["batch_id"])
            return {"match_results": []}

        t0 = time.monotonic()
        match_results = [self._score_context(ctx) for ctx in contexts]
        elapsed_ms = (time.monotonic() - t0) * 1000

        log.info(
            "phase_complete",
            phase=3,
            batch_id=state["batch_id"],
            contexts_in=len(contexts),
            results_out=len(match_results),
            fast_track=sum(1 for r in match_results if r.route == RouteLabel.FAST_TRACK),
            deep_reason=sum(1 for r in match_results if r.route == RouteLabel.DEEP_REASON),
            gap_confirm=sum(1 for r in match_results if r.route == RouteLabel.GAP_CONFIRM),
            latency_ms=round(elapsed_ms, 1),
        )
        return {"match_results": match_results}

    # ------------------------------------------------------------------
    # Per-context scoring
    # ------------------------------------------------------------------

    def _score_context(self, ctx: AssembledContext) -> MatchResult:
        atom = ctx.atom
        caps = ctx.capabilities
        priors: list[PriorFitment] = ctx.prior_fitments

        if not caps:
            log.debug(
                "matching_no_capabilities",
                atom_id=atom.atom_id,
                route=RouteLabel.GAP_CONFIRM,
            )
            return MatchResult(
                atom=atom,
                ranked_capabilities=[],
                composite_scores=[],
                route=RouteLabel.GAP_CONFIRM,
                top_composite_score=0.0,
            )

        # Batch embed: atom text first, then all cap descriptions
        all_texts = [atom.requirement_text] + [c.description for c in caps]
        raw_vecs = np.array(self._get_embedder().embed_batch(all_texts), dtype=np.float32)
        normed = _normalise(raw_vecs)
        atom_norm: np.ndarray = normed[0]    # (d,)  # type: ignore[type-arg]
        cap_norms: np.ndarray = normed[1:]   # (n, d)  # type: ignore[type-arg]

        # Cosines: dot product of atom with each cap (already L2-normalised)
        cosines: list[float] = (cap_norms @ atom_norm).tolist()

        has_history = bool(priors)
        has_fit_prior = any(pf.classification == "FIT" for pf in priors)
        hist_signal = 1.0 if has_history else 0.0

        # (composite, anomaly_flags, updated_cap, original_index)
        scored: list[tuple[float, list[str], RankedCapability, int]] = []

        for i, cap in enumerate(caps):
            cap_lookup_text = f"{cap.feature} {cap.description}"
            signals: dict[str, float] = {
                "embedding_cosine": cosines[i],
                "entity_overlap": _entity_overlap_score(atom.entity_hints, cap_lookup_text),
                "token_ratio": _token_ratio_score(atom.requirement_text, cap.description),
                "historical_alignment": hist_signal,
                "rerank_score": cap.rerank_score,
            }
            composite = _compute_composite(signals)
            if has_fit_prior:
                composite = min(1.0, composite + _HISTORY_BOOST)

            flags: list[str] = []
            anomaly = _detect_anomaly(signals["embedding_cosine"], signals["entity_overlap"])
            if anomaly:
                flags.append(anomaly)

            updated_cap = cap.model_copy(update={"composite_score": composite})
            scored.append((composite, flags, updated_cap, i))

        # Sort highest composite first
        scored.sort(key=lambda x: x[0], reverse=True)

        # Dedup: drop lower-scored caps that are near-duplicates of a higher one
        keep: list[bool] = [True] * len(scored)
        for a_out in range(len(scored)):
            if not keep[a_out]:
                continue
            orig_a = scored[a_out][3]
            for b_out in range(a_out + 1, len(scored)):
                if not keep[b_out]:
                    continue
                orig_b = scored[b_out][3]
                if float(cap_norms[orig_a] @ cap_norms[orig_b]) > _DEDUP_THRESHOLD:
                    keep[b_out] = False

        final = [(s, f, c) for (s, f, c, _), ok in zip(scored, keep) if ok]

        final_scores = [s for s, _, _ in final]
        final_caps = [c for _, _, c in final]
        all_flags = [flag for _, flags, _ in final for flag in flags]

        top_score = final_scores[0] if final_scores else 0.0
        route = _assign_route(top_score, has_history)

        return MatchResult(
            atom=atom,
            ranked_capabilities=final_caps,
            composite_scores=final_scores,
            route=route,
            top_composite_score=top_score,
            anomaly_flags=all_flags,
        )


# ---------------------------------------------------------------------------
# Module-level singleton + LangGraph entry point
# ---------------------------------------------------------------------------

_node: MatchingNode | None = None


def matching_node(state: DynafitState) -> dict[str, Any]:
    """LangGraph Phase 3 node — delegates to the cached MatchingNode instance.

    Tests should instantiate MatchingNode directly with mock dependencies
    instead of calling this function.
    """
    global _node
    if _node is None:
        _node = MatchingNode()
    return _node(state)
