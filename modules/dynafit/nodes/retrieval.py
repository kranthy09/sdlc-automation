"""
Retrieval node — Phase 2 of the DYNAFIT pipeline (Session D).

Responsibility: list[ValidatedAtom] → list[AssembledContext]

Pipeline:
  1. Query builder    — dense vector + BM25 sparse + metadata filter per atom
  2. Parallel retrieval — Source A (Qdrant caps) + Source B (MS Learn docs)
                         + Source C (pgvector history) via asyncio.gather, 5s timeout
  3. RRF / doc boost  — Qdrant already RRF-fuses A internally; apply +0.05 doc boost
  4. Cross-encoder rerank → adaptive Top-K (largest gap in ranks 3–7) + calibration
  5. Context assembly → AssembledContext with SHA-256 provenance hash

Design notes:
  - Batch embeddings: one embed_batch() call per phase invocation (not per atom)
  - Batch BM25:       one BM25Retriever built from all atom texts (meaningful IDF)
  - Async bridge:     asyncio.run() used inside the sync LangGraph node so the
                      graph.invoke() API stays synchronous; guarded against an
                      already-running loop via a thread pool fallback
  - Inject infra:     pass embedder / vector_store / reranker / postgres to
                      RetrievalNode.__init__ in tests instead of touching real infra
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from prometheus_client import CollectorRegistry

from platform.config.settings import get_settings
from platform.observability.logger import get_logger
from platform.retrieval.bm25 import BM25Retriever
from platform.retrieval.embedder import Embedder
from platform.retrieval.reranker import RerankResult, Reranker
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

from ..state import DynafitState

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-12-v2"
_SOURCE_TIMEOUT = 5.0   # per-source asyncio.wait_for timeout (seconds)
_DOC_BOOST = 0.05       # fixed score boost when a doc chunk confirms a capability
_CE_THRESHOLD = 0.5     # top-1 score threshold used in retrieval quality classification
_GAP_LO = 3             # adaptive-K: search for largest score gap starting at rank 3
_GAP_HI = 7             # adaptive-K: stop searching after rank 7

# ---------------------------------------------------------------------------
# ProductConfig helper  (MVP: d365_fo only)
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
# Async bridge — safe to call from sync or async contexts
# ---------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="retrieval")


def _run_async(coro: Any) -> Any:
    """Run a coroutine from a synchronous context.

    If an event loop is already running (e.g. inside graph.ainvoke()),
    submit the coroutine to a thread that owns a fresh event loop so we
    never block the caller's loop.
    """
    try:
        asyncio.get_running_loop()
        # Already inside an event loop — run in a separate thread
        return _executor.submit(asyncio.run, coro).result(timeout=_SOURCE_TIMEOUT * 3 + 5)
    except RuntimeError:
        # No running loop — safe to call asyncio.run() directly
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Step 2: Parallel retrieval (all three sources concurrently)
# ---------------------------------------------------------------------------


def _parallel_retrieve(
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

    async def _gather() -> tuple[list[SearchHit], list[SearchHit], list[PriorFitment]]:
        caps_task = asyncio.to_thread(
            store.search,
            cap_collection,
            dense_vec,
            top_k_caps,
            payload_filter=module_filter,
            sparse=sparse,
        )
        docs_task = asyncio.to_thread(
            store.search,
            doc_collection,
            dense_vec,
            10,
        )
        history_task = postgres.get_similar_fitments(dense_vec, 5, module=module)

        raw = await asyncio.gather(
            asyncio.wait_for(caps_task, timeout=_SOURCE_TIMEOUT),
            asyncio.wait_for(docs_task, timeout=_SOURCE_TIMEOUT),
            asyncio.wait_for(history_task, timeout=_SOURCE_TIMEOUT),
            return_exceptions=True,
        )
        caps_res, docs_res, hist_res = raw

        caps: list[SearchHit] = caps_res if isinstance(caps_res, list) else []
        docs: list[SearchHit] = docs_res if isinstance(docs_res, list) else []
        priors: list[PriorFitment] = hist_res if isinstance(hist_res, list) else []

        if not isinstance(caps_res, list):
            log.warning("retrieval_source_a_failed", error=str(caps_res))
        if not isinstance(docs_res, list):
            log.warning("retrieval_source_b_failed", error=str(docs_res))
        if not isinstance(hist_res, list):
            log.warning("retrieval_source_c_failed", error=str(hist_res))

        return caps, docs, priors

    return _run_async(_gather())


# ---------------------------------------------------------------------------
# Step 3: RRF / doc boost
# ---------------------------------------------------------------------------


def _rrf_boost(
    caps_hits: list[SearchHit],
    doc_hits: list[SearchHit],
) -> list[SearchHit]:
    """Apply +0.05 doc boost to capabilities confirmed by a Source B doc chunk.

    Qdrant already performs internal RRF on the hybrid (dense+sparse) query for
    Source A.  This step only applies the fixed doc boost described in the spec,
    then re-sorts by the boosted score.
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
            feature in mention or mention in feature
            for mention in doc_mentions
            if mention
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
        composite_score=composite_score,
        rerank_score=rerank_score,
        bm25_score=0.0,  # Phase 3 computes the 5-signal composite; bm25 unknown here
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

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder("BAAI/bge-large-en-v1.5")
        return self._embedder

    def _get_store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore(get_settings().qdrant_url)
        return self._store

    def _get_reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = Reranker(_RERANKER_MODEL)
        return self._reranker

    def _get_postgres(self) -> PostgresStore:
        if self._postgres is None:
            self._postgres = PostgresStore(get_settings().postgres_url)
        return self._postgres

    # ------------------------------------------------------------------
    # LangGraph entry point
    # ------------------------------------------------------------------

    def __call__(self, state: DynafitState) -> dict[str, Any]:
        batch_id: str = state["batch_id"]
        atoms: list[ValidatedAtom] = state.get("validated_atoms", [])  # type: ignore[assignment]
        upload = state["upload"]
        t0 = time.monotonic()

        log.info("phase_start", phase=2, batch_id=batch_id, atom_count=len(atoms))

        if not atoms:
            log.info("phase_complete", phase=2, batch_id=batch_id, contexts=0, latency_ms=0)
            return {"retrieval_contexts": []}

        config = _get_product_config(upload.product_id)
        contexts = self._run(atoms, config)

        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "phase_complete",
            phase=2,
            batch_id=batch_id,
            atoms_in=len(atoms),
            contexts_out=len(contexts),
            latency_ms=round(elapsed_ms, 1),
        )
        return {"retrieval_contexts": contexts}

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def _run(
        self,
        atoms: list[ValidatedAtom],
        config: ProductConfig,
    ) -> list[AssembledContext]:
        embedder = self._get_embedder()
        store = self._get_store()
        reranker = self._get_reranker()
        postgres = self._get_postgres()

        # Batch embed (one model call for all atoms)
        atom_texts = [a.requirement_text for a in atoms]
        dense_vecs = embedder.embed_batch(atom_texts)

        # Batch BM25 — IDF weights are meaningful across the whole requirement set.
        # Fresh registry per invocation prevents Prometheus duplicate-counter errors
        # when the node is called multiple times in the same process (e.g. tests).
        bm25 = BM25Retriever(corpus=atom_texts, registry=CollectorRegistry())

        return [
            self._retrieve_one(atom, dense_vec, bm25, store, reranker, postgres, config)
            for atom, dense_vec in zip(atoms, dense_vecs, strict=True)
        ]

    def _retrieve_one(
        self,
        atom: ValidatedAtom,
        dense_vec: list[float],
        bm25: BM25Retriever,
        store: VectorStore,
        reranker: Reranker,
        postgres: PostgresStore,
        config: ProductConfig,
    ) -> AssembledContext:
        t0 = time.monotonic()

        # ── Step 1: Query builder ────────────────────────────────────────────
        top_k = 30 if atom.content_type == "image_derived" else 20
        sparse_indices, sparse_values = bm25.encode(atom.requirement_text)
        module_filter: dict[str, str | int | float | bool] = {"module": atom.module}

        # ── Step 2: Parallel retrieval ───────────────────────────────────────
        caps_hits, doc_hits, prior_fitments = _parallel_retrieve(
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

        # ── Step 3: Doc boost ────────────────────────────────────────────────
        fused = _rrf_boost(caps_hits, doc_hits)

        # ── Step 4: Cross-encoder rerank ─────────────────────────────────────
        candidates = [
            (h.id, h.payload.get("description", "") or h.payload.get("feature", ""))
            for h in fused
        ]
        reranked = reranker.rerank(atom.requirement_text, candidates, top_k=len(candidates))

        k = _adaptive_k(reranked)
        top = reranked[:k]

        has_history = bool(prior_fitments)
        quality = _retrieval_quality(top, has_history)
        quality_mult = {"HIGH": 1.0, "MEDIUM": 0.85, "LOW": 0.70}[quality]
        history_boost = 1.1 if has_history else 1.0

        # Map fused hit id → SearchHit for payload lookup
        hit_index: dict[str | int, SearchHit] = {h.id: h for h in fused}

        ranked_capabilities: list[RankedCapability] = []
        for r in top:
            hit = hit_index.get(r.id)
            if hit is None:
                continue
            calibrated = min(1.0, r.score * quality_mult * history_boost)
            ranked_capabilities.append(_hit_to_ranked_capability(hit, calibrated, r.score))

        # Token budget: trim capability descriptions to avoid overflow in Phase 4 prompts
        _trim_descriptions(ranked_capabilities, token_budget=3072)

        # ── Step 5: Context assembly ─────────────────────────────────────────
        prov_input = atom.atom_id + "".join(c.capability_id for c in ranked_capabilities)
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


def _trim_descriptions(caps: list[RankedCapability], token_budget: int) -> None:
    """Trim capability descriptions in-place so they fit within the token budget.

    Approximates tokens as chars / 4.  Trims the longest descriptions first,
    always preserving the feature name intact.  Mutates the Pydantic models via
    object.__setattr__ since RankedCapability is frozen.
    """
    total = sum(len(c.description) for c in caps)
    budget_chars = token_budget * 4

    if total <= budget_chars:
        return

    # Sort by description length descending, trim the longest first
    order = sorted(range(len(caps)), key=lambda i: len(caps[i].description), reverse=True)
    for idx in order:
        cap = caps[idx]
        excess = sum(len(c.description) for c in caps) - budget_chars
        if excess <= 0:
            break
        trim_to = max(80, len(cap.description) - excess)
        object.__setattr__(cap, "description", cap.description[:trim_to] + "…")


# ---------------------------------------------------------------------------
# Module-level node function (LangGraph wiring)
# ---------------------------------------------------------------------------

_node: RetrievalNode | None = None


def retrieval_node(state: DynafitState) -> dict[str, Any]:
    """Phase 2 LangGraph node — delegates to the cached RetrievalNode instance.

    Tests should instantiate RetrievalNode directly with mock dependencies
    instead of calling this function.
    """
    global _node
    if _node is None:
        _node = RetrievalNode()
    return _node(state)
