# Phase 2 — RAG (Retrieval-Augmented Generation)

**What:** Find similar requirements from knowledge base for each atom.

**File:** `modules/dynafit/nodes/phase2_rag.py`

**Input:** `AtomizedBatch`

**Output:** `list[RetrievalResult]` — Similar atoms per requirement

---

## What It Does

For each requirement atom:
1. Search vector store (Qdrant) for similar requirements
2. Use hybrid search: dense embeddings (60%) + BM25 (40%)
3. Rerank top-10 with cross-encoder
4. Return top-5 with scores

## Output Schema

```python
class RetrievalResult(BaseModel):
    atom_id: str  # Which requirement
    similar_atoms: list[RequirementAtom]  # From KB
    scores: list[float]  # Ranking scores (0.0-1.0)
    rank: int  # Position in final results
```

## Implementation Pattern

```python
async def phase2_rag(batch: AtomizedBatch) -> list[RetrievalResult]:
    """
    For each atom in batch:
      1. Call search_requirements (retrieval platform)
      2. Collect results
    Return list of RetrievalResult
    """

    results = []
    for atom in batch.atoms:
        # Search KB
        similar = await search_requirements(
            query_text=atom.text,
            top_k=5,
            filters={"country": atom.country} if atom.country else None
        )

        # Log
        logger.info("rag_search_completed", atom_id=atom.id, count=len(similar))

        # Add result
        results.append(RetrievalResult(
            atom_id=atom.id,
            similar_atoms=[r.atom for r in similar],
            scores=[r.score for r in similar],
            rank=1  # Just first result
        ))

    return results
```

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

Must be populated before Phase 2 runs:

```bash
# Load seed data
python -m modules.dynafit.load_kb

# Verify
curl -s http://localhost:6333/collections/requirements
```

**KB sources:**
- `knowledge_bases/d365_fo/seed_data/` — Pre-built atoms
- `knowledge_bases/d365_fo/country_rules/` — Country configs
- `knowledge_bases/d365_fo/fdd_templates/` — Feature definitions

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

    # At least one result should have similar atoms
    assert any(len(r.similar_atoms) > 0 for r in results)
```

## Metrics

Auto-tracked:
```
retrieval_search_duration_seconds
retrieval_results_count
retrieval_rerank_score_avg
```

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — Node pattern
- [retrieval.md](../platform/retrieval.md) — Vector search details
- `knowledge_bases/d365_fo/` — KB structure
