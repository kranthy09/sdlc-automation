"""
Classification node — Phase 4 of the DYNAFIT pipeline (Session F, part F2).

Responsibility: list[MatchResult] → list[ClassificationResult]

Pipeline:
  1. Short-circuit: zero capabilities → auto-GAP
     (no LLM call, llm_calls_used=0)
  2. G8 prompt firewall: render_prompt("classification_v1.j2") — autoescape +
     StrictUndefined + whitelist enforced in loader
  3. LLM reasoning by route (from Phase 3 RouteLabel):
       FAST_TRACK   → 1 call, temperature=0.0
       DEEP_REASON  → 3 calls, temperature=0.3, majority vote;
                      all-disagree or <2 successes → REVIEW_REQUIRED
       GAP_CONFIRM  → 1 call, temperature=0.0
  4. G9 output schema: LLMClassificationOutput via Anthropic tool-use in
     LLMClient.complete() — retries (max 3) handled inside the client.
     On final LLMError → classification=REVIEW_REQUIRED
  5. Sanity checks (score-vs-verdict consistency):
       FIT   + composite < _FIT_SANITY_MIN (0.50) → demote to PARTIAL_FIT
       GAP   + composite > config.fit_confidence_threshold → REVIEW_REQUIRED

Design:
  - No direct anthropic import — LLM calls go through platform/llm/client.py.
  - prior_fitments for the prompt are pulled from state["retrieval_contexts"],
    keyed by atom_id (Phase 2 populated, Phase 3 did not carry them forward).
  - ClassificationNode accepts injectable llm_client for tests.
  - Module-level singleton + classification_node() mirrors matching.py pattern.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from platform.llm.client import LLMClient, LLMError
from platform.observability.logger import get_logger
from platform.schemas.fitment import (
    ClassificationResult,
    FitLabel,
    MatchResult,
    RouteLabel,
)
from platform.schemas.product import ProductConfig
from platform.schemas.retrieval import PriorFitment
from platform.storage.redis_pub import RedisPubSub

from ..events import (
    publish_classification_event,
    publish_phase_complete,
    publish_phase_start,
    publish_step_progress,
)
from ..product_config import get_product_config
from ..prompts.loader import render_prompt
from ..state import DynafitState

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# FIT verdict with a composite below this is implausibly strong — demote
_FIT_SANITY_MIN: float = 0.50

# Number of independent LLM calls for DEEP_REASON majority vote
_DEEP_REASON_CALLS: int = 3


# ---------------------------------------------------------------------------
# LLM output schema  (G9 — tool-use enforced by LLMClient)
# ---------------------------------------------------------------------------


class LLMClassificationOutput(BaseModel):
    """Fields the LLM fills in via Anthropic tool-use.

    Constrains verdicts to the three actionable outcomes only — REVIEW_REQUIRED
    is a system decision the node assigns; the LLM never chooses it.
    """

    verdict: Literal["FIT", "PARTIAL_FIT", "GAP"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    d365_capability_ref: str = ""
    config_steps: str = ""  # populated by LLM when verdict=PARTIAL_FIT
    configuration_steps: list[str] = Field(
        default_factory=list,
    )  # PARTIAL_FIT: numbered config actions
    gap_description: str = ""  # populated by LLM when verdict=GAP
    dev_effort: Literal["S", "M", "L"] | None = None  # GAP only
    gap_type: str = ""  # GAP: Extension / Integration / New feature
    caveats: str = ""


# ---------------------------------------------------------------------------
# ClassificationNode
# ---------------------------------------------------------------------------


class ClassificationNode:
    """Phase 4 LLM classification pipeline with injectable dependencies.

    In tests, inject a mock LLM client directly:

        node = ClassificationNode(llm_client=make_llm_client(output1, output2))
        result = node(state)

    Production uses the module-level ``classification_node`` singleton which
    lazily initialises ClassificationNode with the default LLMClient.

    Args:
        llm_client:     LLMClient instance. Lazily initialised if not provided.
        product_config: Override the product config (useful in tests to fix
                        thresholds without environment variables).
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        product_config: ProductConfig | None = None,
        redis: RedisPubSub | None = None,
    ) -> None:
        self._llm = llm_client
        self._config_override = product_config
        self._redis = redis

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _get_redis(self) -> RedisPubSub:
        if self._redis is None:
            from platform.config.settings import get_settings  # noqa: PLC0415

            self._redis = RedisPubSub(get_settings().redis_url)
        return self._redis

    def _get_config(
        self, product_id: str, overrides: dict[str, Any] | None = None
    ) -> ProductConfig:
        base = self._config_override if self._config_override is not None else get_product_config(product_id)
        if overrides:
            recognized = {k: v for k, v in overrides.items() if hasattr(base, k)}
            if recognized:
                return base.model_copy(update=recognized)
        return base

    # ------------------------------------------------------------------
    # LangGraph entry point
    # ------------------------------------------------------------------

    def __call__(self, state: DynafitState) -> dict[str, Any]:
        match_results: list[MatchResult] = (  # type: ignore[assignment]
            state.get("match_results", [])
        )
        if not match_results:
            log.debug(
                "classification_skipped_no_match_results",
                batch_id=state["batch_id"],
            )
            return {"classifications": []}

        batch_id: str = state["batch_id"]
        config = self._get_config(state["upload"].product_id, state.get("config_overrides"))

        publish_phase_start(
            batch_id, self._get_redis(),
            phase=4, phase_name="Classification",
        )

        # Build prior_fitments lookup from Phase 2 AssembledContexts.
        # Phase 3 (MatchResult) does not carry prior_fitments forward,
        # so we cross-reference state["retrieval_contexts"] by atom_id.
        priors_by_atom: dict[str, list[PriorFitment]] = {
            ctx.atom.atom_id: ctx.prior_fitments
            for ctx in state.get(  # type: ignore[call-overload]
                "retrieval_contexts", []
            )
        }

        t0 = time.monotonic()
        n = len(match_results)
        classifications: list[ClassificationResult] = []
        for i, mr in enumerate(match_results):
            result = self._classify_one(
                mr,
                priors_by_atom.get(mr.atom.atom_id, []),
                config,
            )
            publish_classification_event(batch_id, result, self._get_redis())
            classifications.append(result)
            publish_step_progress(
                batch_id, self._get_redis(),
                phase=4,
                step=f"Classifying requirements ({i + 1}/{n})",
                completed=i + 1,
                total=n,
            )
        elapsed_ms = (time.monotonic() - t0) * 1000

        counts: Counter[FitLabel] = Counter(r.classification for r in classifications)
        atoms_flagged = counts.get(FitLabel.REVIEW_REQUIRED, 0)
        atoms_validated = len(classifications) - atoms_flagged
        log.info(
            "phase_complete",
            phase=4,
            batch_id=batch_id,
            atoms_in=len(match_results),
            fit=counts.get(FitLabel.FIT, 0),
            partial_fit=counts.get(FitLabel.PARTIAL_FIT, 0),
            gap=counts.get(FitLabel.GAP, 0),
            review=atoms_flagged,
            latency_ms=round(elapsed_ms, 1),
        )
        publish_phase_complete(
            batch_id, self._get_redis(),
            phase=4, phase_name="Classification",
            atoms_produced=len(classifications),
            atoms_validated=atoms_validated,
            atoms_flagged=atoms_flagged,
            latency_ms=round(elapsed_ms, 1),
        )
        return {"classifications": classifications}

    # ------------------------------------------------------------------
    # Per-atom orchestration
    # ------------------------------------------------------------------

    def _classify_one(
        self,
        mr: MatchResult,
        prior_fitments: list[PriorFitment],
        config: ProductConfig,
    ) -> ClassificationResult:
        atom = mr.atom

        # Short-circuit: no capabilities retrieved → GAP, no LLM call
        if not mr.ranked_capabilities:
            log.debug(
                "classification_shortcircuit_no_caps",
                atom_id=atom.atom_id,
            )
            return ClassificationResult(
                atom_id=atom.atom_id,
                requirement_text=atom.requirement_text,
                module=atom.module,
                country=atom.country,
                wave=atom.wave,
                classification=FitLabel.GAP,
                confidence=1.0,
                rationale=("No matching D365 capability found in knowledge base."),
                route_used=mr.route,
                llm_calls_used=0,
            )

        if mr.route == RouteLabel.FAST_TRACK:
            result = self._fast_track(mr, prior_fitments, config)
        elif mr.route == RouteLabel.DEEP_REASON:
            result = self._deep_reason(mr, prior_fitments, config)
        else:
            result = self._gap_confirm(mr, prior_fitments, config)

        return self._apply_sanity_checks(result, mr, config)

    # ------------------------------------------------------------------
    # Route strategies
    # ------------------------------------------------------------------

    def _fast_track(
        self,
        mr: MatchResult,
        priors: list[PriorFitment],
        config: ProductConfig,
    ) -> ClassificationResult:
        try:
            out = self._call_llm(mr, priors, config, temperature=0.0)
        except LLMError as exc:
            log.warning(
                "classification_llm_error",
                route="FAST_TRACK",
                atom_id=mr.atom.atom_id,
                error=str(exc),
            )
            return self._make_review_required(mr, f"LLM error on FAST_TRACK route: {exc}")
        return self._assemble(out, mr, llm_calls=1)

    def _gap_confirm(
        self,
        mr: MatchResult,
        priors: list[PriorFitment],
        config: ProductConfig,
    ) -> ClassificationResult:
        try:
            out = self._call_llm(mr, priors, config, temperature=0.0)
        except LLMError as exc:
            log.warning(
                "classification_llm_error",
                route="GAP_CONFIRM",
                atom_id=mr.atom.atom_id,
                error=str(exc),
            )
            return self._make_review_required(mr, f"LLM error on GAP_CONFIRM route: {exc}")
        return self._assemble(out, mr, llm_calls=1)

    def _deep_reason(
        self,
        mr: MatchResult,
        priors: list[PriorFitment],
        config: ProductConfig,
    ) -> ClassificationResult:
        outputs: list[LLMClassificationOutput] = []
        for i in range(_DEEP_REASON_CALLS):
            try:
                out = self._call_llm(mr, priors, config, temperature=0.3)
                outputs.append(out)
            except LLMError as exc:
                log.warning(
                    "classification_deep_reason_call_failed",
                    atom_id=mr.atom.atom_id,
                    call_number=i + 1,
                    error=str(exc),
                )

        if len(outputs) < 2:
            return self._make_review_required(
                mr,
                f"DEEP_REASON: only {len(outputs)}/{_DEEP_REASON_CALLS} LLM calls succeeded",
            )

        vote_counts: Counter[str] = Counter(o.verdict for o in outputs)
        majority_verdict, majority_count = vote_counts.most_common(1)[0]

        if majority_count < 2:
            log.info(
                "classification_deep_reason_no_majority",
                atom_id=mr.atom.atom_id,
                votes=dict(vote_counts),
            )
            return self._make_review_required(
                mr,
                "DEEP_REASON: 3 independent LLM calls produced 3 different "
                "verdicts — no majority reached",
            )

        # Take the rationale from the first response that matches the majority
        winner = next(o for o in outputs if o.verdict == majority_verdict)
        return self._assemble(out=winner, mr=mr, llm_calls=len(outputs))

    # ------------------------------------------------------------------
    # LLM call helper
    # ------------------------------------------------------------------

    def _call_llm(
        self,
        mr: MatchResult,
        priors: list[PriorFitment],
        config: ProductConfig,
        temperature: float,
    ) -> LLMClassificationOutput:
        prompt = render_prompt(
            "classification_v1.j2",
            atom=mr.atom,
            capabilities=mr.ranked_capabilities,
            prior_fitments=priors,
        )
        return self._get_llm().complete(  # type: ignore[return-value]
            prompt,
            LLMClassificationOutput,
            config,
            temperature=temperature,
        )

    # ------------------------------------------------------------------
    # Result assembly
    # ------------------------------------------------------------------

    def _assemble(
        self,
        out: LLMClassificationOutput,
        mr: MatchResult,
        llm_calls: int,
    ) -> ClassificationResult:
        atom = mr.atom
        return ClassificationResult(
            atom_id=atom.atom_id,
            requirement_text=atom.requirement_text,
            module=atom.module,
            country=atom.country,
            wave=atom.wave,
            classification=FitLabel(out.verdict),
            confidence=out.confidence,
            rationale=out.rationale,
            d365_capability_ref=out.d365_capability_ref or None,
            config_steps=out.config_steps or None,
            configuration_steps=out.configuration_steps or None,
            gap_description=out.gap_description or None,
            dev_effort=out.dev_effort,
            gap_type=out.gap_type or None,
            caveats=out.caveats or None,
            route_used=mr.route,
            llm_calls_used=llm_calls,
        )

    def _make_review_required(
        self,
        mr: MatchResult,
        reason: str,
    ) -> ClassificationResult:
        atom = mr.atom
        return ClassificationResult(
            atom_id=atom.atom_id,
            requirement_text=atom.requirement_text,
            module=atom.module,
            country=atom.country,
            wave=atom.wave,
            classification=FitLabel.REVIEW_REQUIRED,
            confidence=0.0,
            rationale=reason,
            route_used=mr.route,
            llm_calls_used=0,
        )

    # ------------------------------------------------------------------
    # Sanity checks  (score-vs-verdict consistency)
    # ------------------------------------------------------------------

    def _apply_sanity_checks(
        self,
        result: ClassificationResult,
        mr: MatchResult,
        config: ProductConfig,
    ) -> ClassificationResult:
        top = mr.top_composite_score
        label = result.classification

        # FIT on a very weak composite score → demote to PARTIAL_FIT
        if label == FitLabel.FIT and top < _FIT_SANITY_MIN:
            log.info(
                "classification_sanity_fit_demoted",
                atom_id=result.atom_id,
                composite=top,
                threshold=_FIT_SANITY_MIN,
            )
            caveat = (
                f"Score-classification inconsistency: FIT verdict on "
                f"composite={top:.2f} (floor {_FIT_SANITY_MIN}). "
                "Demoted to PARTIAL_FIT."
            )
            return result.model_copy(
                update={
                    "classification": FitLabel.PARTIAL_FIT,
                    "caveats": caveat,
                }
            )

        # GAP on a very strong composite score → possible LLM error, flag
        if label == FitLabel.GAP and top > config.fit_confidence_threshold:
            log.info(
                "classification_sanity_gap_flagged",
                atom_id=result.atom_id,
                composite=top,
                threshold=config.fit_confidence_threshold,
            )
            caveat = (
                f"Score-classification inconsistency: GAP verdict on "
                f"composite={top:.2f} "
                f"(threshold {config.fit_confidence_threshold}). "
                "Possible LLM error — flagged for human review."
            )
            return result.model_copy(
                update={
                    "classification": FitLabel.REVIEW_REQUIRED,
                    "caveats": caveat,
                }
            )

        return result


# ---------------------------------------------------------------------------
# Module-level singleton + LangGraph entry point
# ---------------------------------------------------------------------------

_node: ClassificationNode | None = None


def classification_node(state: DynafitState) -> dict[str, Any]:
    """LangGraph Phase 4 node — delegates to the cached ClassificationNode.

    Tests should instantiate ClassificationNode directly with mock
    dependencies instead of calling this function.
    """
    global _node
    if _node is None:
        _node = ClassificationNode()
    return _node(state)
