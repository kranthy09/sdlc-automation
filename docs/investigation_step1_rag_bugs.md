---
name: Step 1 + RAG Pipeline Critical Bugs Investigation
description: Full analysis of why ingestion produces only 1 requirement and RAG returns GAP 0% — 4 critical bugs found (2026-04-03)
type: project
---

# Step 1 (Ingestion) + RAG Pipeline Bug Investigation

**Date**: 2026-04-03
**Symptoms reported**:
1. Text-only file produces only ONE requirement after Step 1
2. After RAG, all requirements show GAP 0% with no D365 capabilities matched
3. This happens for all uploaded files

## Critical Bugs Found (4 bugs, all interacting)

---

### BUG 1: RRF Fusion ID Collision — Capabilities Overwritten by Docs (SMOKING GUN for GAP 0%)

**Files**: `modules/dynafit/nodes/rrf_fusion.py:197-219`, `knowledge_bases/d365_fo/capabilities_lite.yaml`, `knowledge_bases/d365_fo/docs_lite.yaml`

**Root Cause**: `capabilities_lite.yaml` and `docs_lite.yaml` use the **same IDs** (e.g., `doc-ap-0001`). In `multi_source_rrf()`, results are stored in a dict keyed by `str(hit.id)`. Capabilities are processed first, then docs OVERWRITE them:

```python
# Source A: Capabilities
all_results["doc-ap-0001"] = RankedResult(source="capability", ...)
# Source B: Docs — OVERWRITES the capability!
all_results["doc-ap-0001"] = RankedResult(source="doc", ...)
```

Then `cap_results = [r for r in rrf_results if r.source == "capability"]` returns EMPTY because all matching IDs were overwritten by docs.

**Impact**: ALL capabilities are lost → reranker gets empty input → 0 capabilities per atom → everything classified as GAP 0%.

**Fix options**:
- A) Rename capability IDs: `cap-ap-0001` instead of `doc-ap-0001` (+ re-seed)
- B) Use composite keys in RRF: `f"{source}:{id}"` instead of `str(id)`
- **Recommended**: Both A + B for defense in depth

---

### BUG 2: SemanticChunker Doesn't Split Oversized Single Elements (Causes "1 requirement" for text files)

**File**: `platform/ingestion/chunker.py:148-155`

**Root Cause**: When a single `UnifiedElement` exceeds `max_tokens` (512), the chunker creates ONE "solo chunk" with the ENTIRE text instead of splitting it:

```python
if elem_tokens > self.max_tokens:
    solo = self._finalize_chunk([element], {element.modality: elem_tokens}, "")
    yield solo  # ONE chunk with ALL text
    continue
```

For text-only files, Docling may produce the entire file as a single TextItem → one DocumentElement → one UnifiedElement → one EnrichedChunk → one requirement text.

Then `_build_classified_requirements` truncates to 2000 chars per batch item, losing most of the document.

**Additionally**: `token_count` is clamped to 600 for schema validation (line 193-198) but the actual text is NOT truncated — misrepresenting the chunk.

**Fix**: Split oversized elements at paragraph/sentence boundaries before yielding chunks. The chunker needs a `_split_oversized_element()` method.

---

### BUG 3: BM25 Vocabulary Mismatch Between Seed Time and Query Time

**Files**: `infra/scripts/seed_knowledge_base.py:116-117`, `modules/dynafit/nodes/retrieval.py:447`

**Root Cause**: At **seed time**, BM25 vocab is built from capability descriptions:
```python
cap_bm25 = BM25Retriever(corpus=cap_descriptions)  # 120 capability texts
si, sv = cap_bm25.encode(desc)  # term "invoice" → index 5
```

At **query time**, BM25 vocab is built from atom texts:
```python
bm25 = BM25Retriever(corpus=atom_texts)  # atom requirement texts
sparse_indices, sparse_values = bm25.encode(atom.requirement_text)  # term "invoice" → index 0
```

The term→index mappings are **completely different**. Qdrant's sparse dot product between query and stored vectors compares indices that represent different terms.

**Impact**: Hybrid search degrades to dense-only (sparse component is noise). May partially explain poor retrieval quality, though dense search should still work.

**Fix**: Either (a) persist BM25 vocab from seed time and load at query time, or (b) remove sparse query vector at retrieval time (use dense-only query, let Qdrant's internal RRF handle caps).

---

### BUG 4: Module Filter Excludes All Capabilities When Module Assignment Is Wrong

**File**: `modules/dynafit/nodes/retrieval.py:524-525`

**Root Cause**: Strict exact-match filter `{"module": atom.module}` on Qdrant search. When atomizer assigns wrong module (especially fallback "OrganizationAdministration"), Qdrant returns 0 capabilities for that module.

This is exacerbated by Bug 2: when the entire document is one chunk, the LLM sees mixed AP/AR/GL/PM content and defaults to "OrganizationAdministration" (very few KB entries for that module).

**Impact**: Even if Bug 1 were fixed, wrong module → empty search results → GAP.

**Fix**: Downstream of Bug 2 fix, but also consider relaxing the filter to a soft signal or removing it.

---

## Secondary Issues

### Dead Code: `_rrf_boost` function
**File**: `modules/dynafit/nodes/retrieval.py:155-200`
The old `_rrf_boost()` function is still defined but `multi_source_rrf()` replaced it. Dead code.

### Missing YAML Fields
**File**: `knowledge_bases/d365_fo/capabilities_lite.yaml`
`_hit_to_ranked_capability` reads `version`, `tags`, `navigation` from payload but seed script doesn't store them. Result: empty strings in UI.

### docs_corpus_lite.yaml is unused
**File**: `knowledge_bases/d365_fo/docs_corpus_lite.yaml`
The seed script loads `docs_lite.yaml`, not `docs_corpus_lite.yaml`. The corpus file has different IDs (doc-tax-XXXX) — possibly intended as additional docs.

---

## Bug Interaction Chain

```
Text file uploaded
    → Docling produces 1 giant TextItem (Bug 2)
    → Chunker yields 1 oversized chunk
    → LLM atomizer receives truncated text, produces 1 atom
    → Module assigned = "OrganizationAdministration" (fallback)
    → Qdrant search filtered by wrong module → 0 caps (Bug 4)
    → Even if caps found, RRF overwrites them with docs (Bug 1)
    → BM25 sparse is noise anyway (Bug 3)
    → 0 capabilities → GAP 0%
```

## Proposed Fix Order

1. **Bug 1 (RRF ID collision)**: Fix YAML IDs or composite keys — immediate fix, no arch change
2. **Bug 2 (Chunker oversized elements)**: Add text splitting in SemanticChunker
3. **Bug 3 (BM25 vocab)**: Remove sparse from query path (simplest)
4. **Bug 4 (Module filter)**: Re-evaluate after 1-3; may self-resolve
