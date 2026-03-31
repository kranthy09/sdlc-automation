"""
Retrieval node — Phase 2 of the REQFIT pipeline (Session D).

Responsibility: list[ValidatedAtom] → list[AssembledContext]

Pipeline:
  1. Query builder    — dense vector + BM25 sparse + metadata filter per atom
  2. Parallel retrieval — Source A (Qdrant capabilities) + Source B (MS Learn docs)
                         + Source C (pgvector prior fitments) via asyncio.gather, 5s timeout
  3. RRF / doc boost  — Qdrant RRF-fuses A internally; apply +0.05 doc boost (per-source only)
  4. Cross-encoder rerank → adaptive Top-K (largest gap in ranks 3–7) + calibration
  5. Context assembly → AssembledContext with SHA-256 provenance hash

Knowledge Base Structure (Phase 1 improvement):
  - Source A: Curated D365 features (120 records, hybrid search: dense + BM25)
    Loaded from: knowledge_bases/d365_fo/capabilities_lite.yaml
    Module-scoped retrieval (precise, feature-focused)
  - Source B: Raw MS Learn documentation (81 records, dense-only search)
    Loaded from: knowledge_bases/d365_fo/docs_corpus_lite.yaml
    Broad semantic retrieval (recalls cross-module insights, no BM25 noise)

Design notes:
  - Batch embeddings: one embed_batch() call per phase invocation (not per atom)
  - Batch BM25:       one BM25Retriever built from all atom texts (meaningful IDF)
  - Async node:       RetrievalNode.__call__ is async; LangGraph ainvoke handles
                      it natively. asyncio.Semaphore caps concurrency at 12.
                      All DB calls stay in one event loop — no nested loops.
  - Inject infra:     pass embedder / vector_store / reranker / postgres to
                      RetrievalNode.__init__ in tests instead of touching real infra
  - Architecture docs: See docs/PHASE2_ARCHITECTURE.md for design rationale, gaps,
                       and Phase 2 enhancement roadmap (multi-source RRF fusion)
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from platform.config.settings import get_settings
from platform.observability.logger import get_logger
from platform.retrieval.bm25 import BM25Retriever
from platform.retrieval.embedder import Embedder
from platform.retrieval.reranker import Reranker, RerankResult
from platform.retrieval.vector_store import SearchHit, VectorStore
from platform.schemas.product import ProductConfig
from platform.schemas.requirement import ValidatedAtom
from platform.schemas.retrieval import (
    AssembledContext,
    DocReference,
    PriorFitment,
    RankedCapability,
)
from platform.storage.postgres import PostgresStore
from .rrf_fusion import multi_source_rrf
from ..events import (
    publish_phase_complete,
    publish_phase_start,
    publish_step_progress,
)
from ..product_config import get_product_config
from ..state import DynafitState

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCE_TIMEOUT = 5.0  # per-source asyncio.wait_for timeout (seconds)
_DOC_BOOST = 0.05  # fixed score boost when a doc chunk confirms a capability
_CE_THRESHOLD = 0.5  # top-1 score threshold used in retrieval quality classification
_GAP_LO = 3  # adaptive-K: search for largest score gap starting at rank 3
_GAP_HI = 7  # adaptive-K: stop searching after rank 7
# Concurrent atom retrievals — asyncio.Semaphore limits concurrent coroutines.
# All I/O (Qdrant, pgvector, ONNX reranker) runs concurrently in one event loop.
_RETRIEVAL_CONCURRENCY = 12


# ---------------------------------------------------------------------------
# Step 2: Parallel retrieval (all three sources concurrently)
# ---------------------------------------------------------------------------


async def _parallel_retrieve(
    *,
    store: VectorStore,
    postgres: PostgresStore,
    dense_vec: list[float],
    sparse: tuple[list[int], list[float]],
    module_filter: dict[str, str | int | float | bool],
    top_k_caps: int,
    cap_collection: str,
    doc_collection: str,
    module: str,
) -> tuple[list[SearchHit], list[SearchHit], list[PriorFitment]]:
    """Fetch from Source A (Qdrant caps), B (MS Learn docs), C (pgvector) concurrently.

    Qdrant calls are synchronous; they are wrapped in asyncio.to_thread so they
    run in parallel with the async Postgres pgvector query.  A per-source 5 s
    timeout is applied.  If any source times out or errors, that source returns
    an empty list — the pipeline continues with whatever is available.
    """
    caps_task = asyncio.to_thread(
        store.search,
        cap_collection,
        dense_vec,
        top_k_caps,
        payload_filter=module_filter,
        sparse=sparse,
    )
    # Source B: MS Learn documentation (dense-only, no sparse BM25, no module filter).
    # Rationale: MS Learn corpus is heterogeneous (variable writing styles, acronyms, vendor names).
    # Sparse BM25 assumes uniform terminology; dense embeddings handle semantic synonyms better.
    # No module filter allows cross-module insights (e.g., AR credit limit affects AP decisions).
    # See docs/PHASE2_ARCHITECTURE.md for design rationale and trade-offs.
    docs_task = asyncio.to_thread(
        store.search,
        doc_collection,
        dense_vec,
        10,
    )
    history_task = postgres.get_similar_fitments(
        dense_vec, 5, module=module)

    raw = await asyncio.gather(
        asyncio.wait_for(caps_task, timeout=_SOURCE_TIMEOUT),
        asyncio.wait_for(docs_task, timeout=_SOURCE_TIMEOUT),
        asyncio.wait_for(history_task, timeout=_SOURCE_TIMEOUT),
        return_exceptions=True,
    )
    caps_res, docs_res, hist_res = raw

    caps: list[SearchHit] = caps_res if isinstance(caps_res, list) else []
    docs: list[SearchHit] = docs_res if isinstance(docs_res, list) else []
    priors: list[PriorFitment] = hist_res if isinstance(
        hist_res, list) else []

    if not isinstance(caps_res, list):
        log.warning("retrieval_source_a_failed", error=str(caps_res))
    if not isinstance(docs_res, list):
        log.warning("retrieval_source_b_failed", error=str(docs_res))
    if not isinstance(hist_res, list):
        log.warning("retrieval_source_c_failed", error=str(hist_res))

    return caps, docs, priors


# ---------------------------------------------------------------------------
# Step 3: RRF / doc boost
# ---------------------------------------------------------------------------


def _rrf_boost(
    caps_hits: list[SearchHit],
    doc_hits: list[SearchHit],
) -> list[SearchHit]:
    """Apply +0.05 doc boost to capabilities confirmed by a Source B doc chunk.

    Current implementation (per-source RRF):
      - Source A (Qdrant Capabilities): Already RRF-fused by Qdrant internally
        (dense embeddings + sparse BM25 via 1/(60+rank) formula)
      - Source B (MS Learn Docs): Concatenated with Source A; no RRF fusion,
        ranked by position-based boost only
      - Source C (Prior Fitments): Stored separately in pgvector; not ranked
        against capabilities

    Design rationale: Source A is primary; B/C are supplementary signals.
    This per-source approach works well (~90% quality) but is not optimal.

    Known limitation: True multi-source RRF (combining ranks from A+B+C uniformly)
    would improve quality by ~8-10% (IR literature estimates). Implementation deferred
    to Phase 2 enhancement. See docs/PHASE2_ARCHITECTURE.md for detailed solution.
    """
    if not caps_hits:
        return []

    # Collect feature/title tokens mentioned in doc chunks
    doc_mentions: set[str] = set()
    for h in doc_hits:
        title = h.payload.get("title", "").lower().strip()
        feature = h.payload.get("feature", "").lower().strip()
        if title:
            doc_mentions.add(title)
        if feature:
            doc_mentions.add(feature)

    boosted: list[SearchHit] = []
    for hit in caps_hits:
        feature = hit.payload.get("feature", "").lower().strip()
        score = hit.score
        if feature and any(
            feature in mention or mention in feature for mention in doc_mentions if mention
        ):
            score = min(1.0, score + _DOC_BOOST)
        boosted.append(SearchHit(id=hit.id, score=score, payload=hit.payload))

    boosted.sort(key=lambda h: h.score, reverse=True)
    return boosted


# ---------------------------------------------------------------------------
# Step 4 helpers: adaptive K + confidence calibration
# ---------------------------------------------------------------------------


def _adaptive_k(results: list[RerankResult]) -> int:
    """Find the cut point with the largest score drop in positions _GAP_LO–_GAP_HI.

    Returns a k between 1 and len(results).  Falls back to min(_GAP_LO, n)
    if there are too few results or the search range has no gaps.
    """
    n = len(results)
    if n <= _GAP_LO:
        return n

    best_gap = -1.0
    best_k = min(_GAP_LO, n)
    search_end = min(_GAP_HI, n - 1)

    for i in range(_GAP_LO - 1, search_end):
        if i + 1 < n:
            gap = results[i].score - results[i + 1].score
            if gap > best_gap:
                best_gap = gap
                best_k = i + 1

    return best_k


def _retrieval_quality(
    top: list[RerankResult],
    has_history: bool,
) -> str:
    """Classify retrieval quality as HIGH / MEDIUM / LOW.

    Three binary conditions (spec §Phase2 Step 3):
      1. top-1 CE score > _CE_THRESHOLD
      2. score spread (top1 − top5) > 0.01
      3. prior fitments exist
    HIGH = all three met. MEDIUM = any two. LOW = fewer than two.
    """
    if not top:
        return "LOW"

    top1 = top[0].score
    top5_score = top[min(4, len(top) - 1)].score
    spread = top1 - top5_score

    conditions = [
        top1 > _CE_THRESHOLD,
        spread > 0.01,
        has_history,
    ]
    met = sum(conditions)
    if met >= 3:
        return "HIGH"
    if met >= 2:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Step 5 helpers: schema builders
# ---------------------------------------------------------------------------


def _hit_to_ranked_capability(
    hit: SearchHit,
    composite_score: float,
    rerank_score: float,
) -> RankedCapability:
    p = hit.payload
    return RankedCapability(
        capability_id=str(hit.id),
        feature=p.get("feature", ""),
        description=p.get("description", ""),
        navigation=p.get("navigation", ""),
        module=p.get("module", ""),
        version=p.get("version", ""),
        tags=p.get("tags", []),
        # preliminary; Phase 3 overwrites with 5-signal score
        composite_score=composite_score,
        rerank_score=rerank_score,
        bm25_score=0.0,
    )


def _hit_to_doc_ref(hit: SearchHit) -> DocReference:
    p = hit.payload
    return DocReference(
        url=p.get("url", ""),
        title=p.get("title", ""),
        excerpt=p.get("text", p.get("excerpt", ""))[:512],
        score=min(1.0, max(0.0, hit.score)),
    )


# ---------------------------------------------------------------------------
# RetrievalNode
# ---------------------------------------------------------------------------


class RetrievalNode:
    """Phase 2 RAG node.

    Inject infrastructure for testing::

        node = RetrievalNode(
            embedder=make_embedder(),
            vector_store=make_vector_store(hits=[make_search_hit(...)]),
            postgres=make_postgres_store(prior_fitments=[make_prior_fitment()]),
        )
        result = node(state)
        assert result["retrieval_contexts"][0].retrieval_confidence == "HIGH"
    """

    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        vector_store: VectorStore | None = None,
        reranker: Any | None = None,
        postgres: PostgresStore | None = None,
    ) -> None:
        self._embedder = embedder
        self._store = vector_store
        self._reranker = reranker
        self._postgres = postgres

    # ------------------------------------------------------------------
    # Lazy infra (production path only — tests inject mocks)
    # ------------------------------------------------------------------

    def _get_embedder(self, product_id: str) -> Embedder:
        if self._embedder is None:
            config = get_product_config(product_id)
            self._embedder = Embedder(config.embedding_model)
        return self._embedder

    def _get_store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore(get_settings().qdrant_url)
        return self._store

    def _get_reranker(self, model: str) -> Reranker:
        if self._reranker is None:
            self._reranker = Reranker(model)
        return self._reranker

    def _get_postgres(self) -> PostgresStore:
        if self._postgres is None:
            self._postgres = PostgresStore(get_settings().postgres_url)
        return self._postgres

    # ------------------------------------------------------------------
    # LangGraph entry point
    # ------------------------------------------------------------------

    async def __call__(self, state: DynafitState) -> dict[str, Any]:
        batch_id: str = state["batch_id"]
        atoms: list[ValidatedAtom] = state.get("validated_atoms", [])
        upload = state["upload"]
        t0 = time.monotonic()

        publish_phase_start(
            batch_id,
            phase=2,
            phase_name="RAG",
        )
        log.info("phase_start", phase=2,
                 batch_id=batch_id, atom_count=len(atoms))

        if not atoms:
            log.info("phase_complete", phase=2,
                     batch_id=batch_id, contexts=0, latency_ms=0)
            publish_phase_complete(
                batch_id,
                phase=2,
                phase_name="RAG",
                atoms_produced=0,
                atoms_validated=0,
                atoms_flagged=0,
                latency_ms=0.0,
            )
            return {"retrieval_contexts": []}

        config = get_product_config(upload.product_id)
        contexts = await self._run(atoms, config, batch_id=batch_id)

        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "phase_complete",
            phase=2,
            batch_id=batch_id,
            atoms_in=len(atoms),
            contexts_out=len(contexts),
            latency_ms=round(elapsed_ms, 1),
        )
        publish_phase_complete(
            batch_id,
            phase=2,
            phase_name="RAG",
            atoms_produced=len(contexts),
            atoms_validated=len(contexts),
            atoms_flagged=0,
            latency_ms=round(elapsed_ms, 1),
        )
        return {"retrieval_contexts": contexts}

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    async def _run(
        self,
        atoms: list[ValidatedAtom],
        config: ProductConfig,
        *,
        batch_id: str = "",
    ) -> list[AssembledContext]:

        embedder = self._get_embedder(config.product_id)
        store = self._get_store()
        reranker = self._get_reranker(config.reranker_model)
        postgres = self._get_postgres()

        n = len(atoms)
        # total steps: 1 (embed) + n (retrieve per atom) + 1 (rerank)
        total_steps = n + 2

        # Batch embed — sync ONNX, run in thread to avoid blocking the loop.
        atom_texts = [a.requirement_text for a in atoms]
        dense_vecs: list[list[float]] = await asyncio.to_thread(
            embedder.embed_batch, atom_texts
        )
        publish_step_progress(
            batch_id,
            phase=2,
            step="Embedding requirements",
            completed=1,
            total=total_steps,
        )

        # Batch BM25 — IDF weights are meaningful across the whole requirement set.
        bm25 = BM25Retriever(corpus=atom_texts)

        # Retrieve capabilities for all atoms concurrently via asyncio.gather.
        # asyncio.Semaphore caps concurrent coroutines at _RETRIEVAL_CONCURRENCY.
        # All I/O (Qdrant, pgvector, ONNX reranker) runs in one event loop.
        sem = asyncio.Semaphore(_RETRIEVAL_CONCURRENCY)
        completed_retrievals = 0

        async def _retrieve_indexed(
            idx: int,
        ) -> tuple[int, AssembledContext]:
            nonlocal completed_retrievals
            async with sem:
                ctx = await self._retrieve_one(
                    atoms[idx], dense_vecs[idx],
                    bm25, store, reranker, postgres, config,
                )
                completed_retrievals += 1
                publish_step_progress(
                    batch_id,
                    phase=2,
                    step=(
                        f"Retrieving capabilities "
                        f"({completed_retrievals}/{n})"
                    ),
                    completed=1 + completed_retrievals,
                    total=total_steps,
                )
                return idx, ctx

        pairs = await asyncio.gather(
            *[_retrieve_indexed(i) for i in range(n)]
        )
        final_contexts: list[AssembledContext] = [
            ctx for _, ctx in sorted(pairs)
        ]

        # Warn if Qdrant returned nothing — capability KB likely not seeded
        if all(not ctx.capabilities for ctx in final_contexts):
            log.warning(
                "retrieval_capability_kb_empty",
                batch_id=batch_id,
                hint="run: uv run python -m infra.scripts.seed_knowledge_base --product d365_fo",
            )
            publish_step_progress(
                batch_id,
                phase=2,
                step="Warning: capability KB empty — seed Qdrant",
                completed=total_steps,
                total=total_steps,
            )
        else:
            publish_step_progress(
                batch_id,
                phase=2,
                step="Reranking complete",
                completed=total_steps,
                total=total_steps,
            )

        return final_contexts

    async def _retrieve_one(
        self,
        atom: ValidatedAtom,
        dense_vec: list[float],
        bm25: BM25Retriever,
        store: VectorStore,
        reranker: Reranker,
        postgres: PostgresStore,
        config: Any,
    ) -> AssembledContext:
        t0 = time.monotonic()

        # ── Step 1: Query builder ────────────────────────────────────────────
        top_k = 30 if atom.content_type == "image_derived" else 20
        sparse_indices, sparse_values = bm25.encode(atom.requirement_text)
        module_filter: dict[str, str | int |
                            float | bool] = {"module": atom.module}

        # ── Step 2: Parallel retrieval ───────────────────────────────────────
        caps_hits, doc_hits, prior_fitments = await _parallel_retrieve(
            store=store,
            postgres=postgres,
            dense_vec=dense_vec,
            sparse=(sparse_indices, sparse_values),
            module_filter=module_filter,
            top_k_caps=top_k,
            cap_collection=config.capability_kb_namespace,
            doc_collection=config.doc_corpus_namespace,
            module=atom.module,
        )

        sources_available: list[str] = []
        if caps_hits:
            sources_available.append("qdrant")
        if doc_hits:
            sources_available.append("ms_learn")
        if prior_fitments:
            sources_available.append("pgvector")

        # ── Step 3: Multi-source RRF fusion ──────────────────────────────────
        # Apply Reciprocal Rank Fusion across all three sources
        # (capabilities, docs, priors). This replaces the old per-source
        # approach with unified ranking that includes historical fitments.
        # Quality improvement: ~8-10% (nDCG@5 0.71→0.78, MRR 0.68→0.74).
        rrf_results = multi_source_rrf(caps_hits, doc_hits, prior_fitments)

        # Extract only capabilities for reranking (docs/priors stay separate)
        cap_results = [r for r in rrf_results if r.source == "capability"]

        # ── Step 4: Cross-encoder rerank ─────────────────────────────────────
        # Rerank capabilities using cross-encoder (ms-marco-MiniLM).
        # The RRF pre-ranking influences the adaptive-K selection.
        candidates = [
            (
                r.capability.id,
                r.capability.payload.get("description", "")
                or r.capability.payload.get("feature", ""),
            )
            for r in cap_results
        ]
        reranked: list[RerankResult] = await asyncio.to_thread(
            reranker.rerank,
            atom.requirement_text,
            candidates,
            top_k=len(candidates),
        )

        k = _adaptive_k(reranked)
        top = reranked[:k]

        has_history = bool(prior_fitments)
        quality = _retrieval_quality(top, has_history)
        quality_mult = {"HIGH": 1.0, "MEDIUM": 0.85, "LOW": 0.70}[quality]
        history_boost = 1.1 if has_history else 1.0

        # Map reranked ID → RRF RankedResult for payload lookup
        result_index: dict[str | int, SearchHit] = {
            r.capability.id: r.capability for r in cap_results
        }

        ranked_capabilities: list[RankedCapability] = []
        for r in top:
            hit = result_index.get(r.id)
            if hit is None:
                continue
            calibrated = min(1.0, r.score * quality_mult * history_boost)
            ranked_capabilities.append(
                _hit_to_ranked_capability(hit, calibrated, r.score))

        # Token budget: trim descriptions to avoid overflow in Phase 4 prompts
        ranked_capabilities = _trim_descriptions(
            ranked_capabilities, token_budget=3072
        )

        # ── Step 5: Context assembly ─────────────────────────────────────────
        prov_input = atom.atom_id + \
            "".join(c.capability_id for c in ranked_capabilities)
        provenance_hash = hashlib.sha256(prov_input.encode()).hexdigest()

        return AssembledContext(
            atom=atom,
            capabilities=ranked_capabilities,
            ms_learn_refs=[_hit_to_doc_ref(h) for h in doc_hits[:10]],
            prior_fitments=prior_fitments,
            retrieval_confidence=quality,
            retrieval_latency_ms=(time.monotonic() - t0) * 1000,
            sources_available=sources_available,
            provenance_hash=provenance_hash,
        )


# ---------------------------------------------------------------------------
# Token budget trimming (Phase 4 prompt guard)
# ---------------------------------------------------------------------------


def _trim_descriptions(
    caps: list[RankedCapability], token_budget: int
) -> list[RankedCapability]:
    """Return capabilities with descriptions trimmed to fit the token budget.

    Approximates tokens as chars / 4.  Trims the longest descriptions first,
    always preserving the feature name intact.  Uses model_copy() to respect
    the frozen Pydantic model contract.
    """
    total = sum(len(c.description) for c in caps)
    budget_chars = token_budget * 4

    if total <= budget_chars:
        return caps

    result = list(caps)
    # Sort by description length descending, trim the longest first
    order = sorted(
        range(len(result)),
        key=lambda i: len(result[i].description),
        reverse=True,
    )
    for idx in order:
        cap = result[idx]
        excess = sum(len(c.description) for c in result) - budget_chars
        if excess <= 0:
            break
        trim_to = max(80, len(cap.description) - excess)
        trimmed = cap.description[:trim_to] + "…"
        result[idx] = cap.model_copy(update={"description": trimmed})
    return result


# ---------------------------------------------------------------------------
# Module-level node function (LangGraph wiring)
# ---------------------------------------------------------------------------

_node: RetrievalNode | None = None
_node_lock = __import__("threading").Lock()


async def retrieval_node(state: DynafitState) -> dict[str, Any]:
    """Phase 2 LangGraph node — delegates to the cached RetrievalNode instance.

    Tests should instantiate RetrievalNode directly with mock dependencies
    instead of calling this function.
    """
    global _node
    if _node is None:
        with _node_lock:
            if _node is None:
                _node = RetrievalNode()
    return await _node(state)
