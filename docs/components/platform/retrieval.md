# Retrieval — Vector Search + BM25

**What:** Hybrid search (dense embeddings + full-text BM25 + cross-encoder reranking).

**Where:** `platform/retrieval/`

**Use in:** Phase 2 (RAG) to find similar requirements.

---

## Core Function

```python
from platform.retrieval import search_requirements

results = await search_requirements(
    query_text=requirement_text,
    top_k=5,
    filters={"country": "US"}
)
# Returns: list[RetrievalResult] ordered by score
```

## What It Does

1. **Dense embedding** — Convert text to vector via fastembed
2. **BM25 search** — Full-text keyword matching
3. **Combine scores** — Hybrid: 60% dense + 40% BM25
4. **Rerank** — Cross-encoder model reorders top-10
5. **Deduplicate** — Remove identical requirements

## Configuration

```
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=requirements
EMBEDDER_MODEL=intfloat/multilingual-e5-small  # fastembed
CROSS_ENCODER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
```

From config:
```python
from platform.config import get_settings
settings = get_settings()
top_k = settings.retrieval_top_k  # Usually 5-10
```

## Filtering

```python
# By country
results = await search_requirements(
    query_text="Sales order process",
    filters={"country": "DE"}
)

# By module
results = await search_requirements(
    query_text="Inventory check",
    filters={"module": "Inventory Management"}
)

# Multiple filters (AND)
results = await search_requirements(
    query_text="...",
    filters={"country": "US", "module": "Sales"}
)
```

## Populating the Knowledge Base

```bash
# Load seed data into Qdrant
python -m modules.dynafit.load_kb

# Verify
curl http://localhost:6333/collections
```

KB sources:
- `knowledge_bases/d365_fo/seed_data/` — Pre-built requirement atoms
- `knowledge_bases/d365_fo/country_rules/` — Country-specific configs
- `knowledge_bases/d365_fo/fdd_templates/` — D365 feature definitions

## Testing

```python
@pytest.mark.asyncio
async def test_search_requirements():
    # Assumes KB is populated
    results = await search_requirements("Sales process", top_k=5)
    assert len(results) <= 5
    assert all(isinstance(r, RetrievalResult) for r in results)
    assert results[0].score >= results[-1].score  # Sorted by score
```

**Live KB test** (mark with `@pytest.mark.integration`):
```python
async def test_search_with_real_kb():
    # Needs docker-compose services running
    results = await search_requirements("Ledger posting", top_k=3)
    assert len(results) > 0
```

## Error Handling

```python
from platform.retrieval import RetrievalError

try:
    results = await search_requirements("...", top_k=5)
except RetrievalError as e:
    logger.error("retrieval_failed", error=str(e))
    # Phase 2: return empty results, continue
    return RetrievalResult(similar_atoms=[])
```

Common errors:
- **Qdrant not running** → `Connection refused`
- **Collection empty** → Returns `[]` (not an error)
- **Invalid filter** → `RetrievalError`

## Metrics

Auto-tracked:
```
retrieval_search_duration_seconds
retrieval_results_count
retrieval_rerank_score_avg
retrieval_errors_total
```

No manual logging needed.

## Libraries

**IMPORTANT: Use fastembed only. Never add sentence-transformers.**

- **fastembed** ✅ — Embeddings + cross-encoder reranking (ONNX, ~50 MB)
- **qdrant-client** — Vector store
- **rank-bm25** — BM25 ranking

**Why:** sentence-transformers depends on PyTorch (~500 MB), 9x larger Docker, slower builds. fastembed uses ONNX with identical output quality. See [DECISIONS.md](../../DECISIONS.md#embedding-library-fastembed-only).

See `platform/retrieval/__init__.py`.

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — How to use in Phase 2
- `modules/dynafit/nodes/phase2_rag.py` — Phase 2 node example
- `knowledge_bases/d365_fo/` — Knowledge base structure
