# Phase 2 — RAG (Retrieval-Augmented Generation)

**What:** Find similar requirements and knowledge from three sources for each atom, fused via multi-source RRF.

**File:** `modules/dynafit/nodes/phase2_rag.py`

**Input:** `AtomizedBatch`

**Output:** `list[RetrievalResult]` — Similar atoms per requirement, ranked via multi-source RRF

---

## What It Does

For each requirement atom:
1. **Parallel search** across three knowledge sources:
   - Source A: D365 Capabilities (hybrid: dense + BM25)
   - Source B: MS Learn Docs (dense only)
   - Source C: Prior Fitments (historical decisions)
2. **Unified RRF fusion** of all three sources
3. **Cross-source boosts** when multiple sources agree
4. **Rerank** top candidates with cross-encoder
5. **Return** top-5 with unified scores

## Output Schema

```python
class RetrievalResult(BaseModel):
    atom_id: str  # Which requirement
    similar_atoms: list[RequirementAtom]  # From KB (now RRF-ranked)
    scores: list[float]  # Unified RRF scores (0.0-1.0)
    rank: int  # Position in final results
    source_details: dict  # (optional) Source breakdown for explainability
```

**Scores:**
- Computed via multi-source RRF formula: `1/(60 + rank)`
- Combines signals from capabilities, docs, and prior fitments
- Cross-source boosts applied when multiple sources agree
- Final score clamped to [0.0, 1.0]

## Implementation Pattern

```python
from modules.dynafit.nodes.rrf_fusion import multi_source_rrf

async def phase2_rag(batch: AtomizedBatch) -> list[RetrievalResult]:
    """
    For each atom in batch:
      1. Parallel search across three sources (capabilities, docs, priors)
      2. Unified RRF fusion of all sources
      3. Cross-encode reranking
    Return list of RetrievalResult with multi-source RRF scores
    """

    results = []
    for atom in batch.atoms:
        # Step 1-2: Parallel retrieval + RRF fusion
        cap_hits = await search_capabilities(atom.text, top_k=20, module=atom.module)
        doc_hits = await search_docs(atom.text, top_k=10)
        prior_fitments = await fetch_prior_fitments(atom.text, module=atom.module, top_k=5)

        # Step 3: Multi-source RRF fusion
        rrf_results = multi_source_rrf(cap_hits, doc_hits, prior_fitments)

        # Extract capabilities (cross-source boost applied)
        cap_results = [r for r in rrf_results if r.source == "capability"]

        # Step 4: Cross-encoder reranking on unified RRF ranking
        candidates = [
            (r.capability.id, r.capability.payload.get("description", ""))
            for r in cap_results
        ]
        reranked = await reranker.rank(atom.text, candidates, top_k=5)

        # Log
        logger.info(
            "rag_search_completed",
            atom_id=atom.id,
            count=len(reranked),
            sources={"capabilities": len(cap_hits), "docs": len(doc_hits), "priors": len(prior_fitments)}
        )

        # Add result
        results.append(RetrievalResult(
            atom_id=atom.id,
            similar_atoms=[r.atom for r in reranked],
            scores=[r.score for r in reranked],
            rank=1
        ))

    return results
```

**Key Changes from Old Approach:**
- **Multi-source retrieval**: All three sources queried in parallel
- **Unified RRF fusion**: `multi_source_rrf()` combines all sources
- **Prior fitments integrated**: Historical human decisions now influence ranking
- **Cross-source boosts**: When multiple sources agree, compound evidence weighting
- **Quality improvement**: +8-10% (nDCG@5 0.71→0.78, MRR 0.68→0.74)

## Filtering

Search can filter by country, module, or both:

```python
# No filter (global search)
similar = await search_requirements("Sales order", top_k=5)

# Filter by country
similar = await search_requirements(
    "Sales order",
    top_k=5,
    filters={"country": "US"}
)

# Multiple filters
similar = await search_requirements(
    "Inventory check",
    top_k=5,
    filters={"country": "DE", "module": "Inventory"}
)
```

## Knowledge Base

Must be populated before Phase 2 runs with three distinct sources:

```bash
# Load separated KB data
python -m infra.scripts.seed_knowledge_base --product d365_fo --reset

# Verify collections exist
curl -s http://localhost:6333/collections | jq '.result[] | select(.name | contains("d365_fo"))'
```

**KB sources:**

| Source | File | Type | Size | Retrieval |
|--------|------|------|------|-----------|
| **A** | `capabilities_lite.yaml` | D365 features | 120 records | Hybrid (dense + BM25) |
| **B** | `docs_corpus_lite.yaml` | MS Learn docs | 81 records | Dense only |
| **C** | pgvector table | Prior fitments | Historical | Dense similarity |

**Files:**
- `knowledge_bases/d365_fo/capabilities_lite.yaml` — Curated D365 capabilities
- `knowledge_bases/d365_fo/docs_corpus_lite.yaml` — Raw MS Learn documentation
- `platform/storage/postgres.py` — Prior fitment storage and retrieval

## Error Handling

```python
from platform.retrieval import RetrievalError

try:
    similar = await search_requirements(atom.text, top_k=5)
except RetrievalError as e:
    logger.error("retrieval_failed", atom_id=atom.id, error=str(e))
    # Continue with empty results
    results.append(RetrievalResult(
        atom_id=atom.id,
        similar_atoms=[],
        scores=[],
        rank=0
    ))
```

## Testing

### RRF Fusion Tests

```bash
# Run integration tests for RRF fusion
pytest tests/integration/test_rrf_fusion.py -v
# Output: 18 passed in 1.25s

# Run validation tests
python -m tests.eval.validate_rrf_integration
# Output: ALL VALIDATION TESTS PASSED ✅

# Measure quality improvement
python -m tests.eval.measure_rrf_improvement
# Output: nDCG@5 +9.9%, MRR +8.8%, Recall@20 +3.7%
```

### Phase 2 Integration Tests

```python
@pytest.mark.asyncio
async def test_phase2_rag():
    batch = factories.make_atomized_batch(atom_count=3)
    results = await phase2_rag(batch)

    assert len(results) == 3
    assert all(isinstance(r, RetrievalResult) for r in results)
    assert results[0].atom_id == batch.atoms[0].id

@pytest.mark.integration
async def test_phase2_with_real_kb():
    # Needs docker-compose up + populated KB
    batch = factories.make_atomized_batch()
    results = await phase2_rag(batch)

    # At least one result should have similar atoms from multi-source RRF
    assert any(len(r.similar_atoms) > 0 for r in results)

    # Scores should reflect multi-source RRF ranking
    for result in results:
        assert all(0.0 <= score <= 1.0 for score in result.scores)
```

**See Also:**
- `tests/integration/test_rrf_fusion.py` — RRF fusion unit tests (18/18 passing)
- `tests/eval/validate_rrf_integration.py` — End-to-end validation (6/6 passing)
- `tests/eval/measure_rrf_improvement.py` — Quality measurement

## Metrics

Auto-tracked:
```
retrieval_search_duration_seconds
retrieval_results_count
retrieval_rerank_score_avg
```

## Performance

**Quality Improvements:**
- nDCG@5: 0.71 → 0.78 (+9.9%)
- MRR: 0.68 → 0.74 (+8.8%)
- Recall@20: 0.82 → 0.85 (+3.7%)
- Success@5: 89% → 97% (+8%)

**Latency:**
- Parallel retrieval: ~100ms (capabilities) + ~100ms (docs) + ~150ms (priors)
- RRF fusion: ~5ms
- Cross-encoder reranking: ~50-100ms
- **Total:** ~200-250ms

**Complexity:**
- RRF fusion: O(n log n) where n ≤ 100 items
- Cross-source matching: O(n*m) where n ≤ 50, m ≤ 5

## See Also

- [PHASE2_ARCHITECTURE.md](../../PHASE2_ARCHITECTURE.md) — Full design and implementation
- [PATTERNS.md](../../guides/PATTERNS.md) — Node pattern
- [retrieval.md](../platform/retrieval.md) — Vector search details
- `modules/dynafit/nodes/rrf_fusion.py` — RRF fusion implementation
