# Phase 3 — Matching

**What:** Find candidate D365 modules/features that might fulfill each requirement.

**File:** `modules/dynafit/nodes/phase3_matching.py`

**Input:** `list[RetrievalResult]` from Phase 2

**Output:** `list[MatchingResult]` — Candidate modules per requirement

---

## What It Does

For each requirement + its similar atoms from KB:
1. Extract referenced D365 modules/features from similar atoms
2. Score each candidate (how often mentioned, importance)
3. Return top candidates sorted by relevance

## Output Schema

```python
class MatchingResult(BaseModel):
    atom_id: str
    candidates: list[ModuleCandidate]  # Top modules/features
    confidence: float  # How confident in these matches

class ModuleCandidate(BaseModel):
    module: str  # D365 area (e.g., "Sales", "Inventory")
    feature: str | None  # Specific feature
    match_count: int  # How many KB atoms mention this
    evidence: list[str]  # Quote snippets from similar atoms
```

## Implementation Pattern

```python
async def phase3_matching(
    retrieval_results: list[RetrievalResult]
) -> list[MatchingResult]:
    """
    For each RetrievalResult:
      1. Extract modules/features from similar_atoms
      2. Score candidates by frequency + importance
      3. Return top candidates
    """

    results = []
    for retrieval in retrieval_results:
        candidates = {}

        # Count module mentions
        for similar_atom in retrieval.similar_atoms:
            module = similar_atom.module
            if not module:
                continue

            if module not in candidates:
                candidates[module] = {
                    "count": 0,
                    "feature": similar_atom.feature,
                    "evidence": []
                }
            candidates[module]["count"] += 1
            candidates[module]["evidence"].append(similar_atom.text[:100])

        # Score and sort
        scored = sorted(
            candidates.items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )[:5]  # Top 5

        confidence = len(retrieval.similar_atoms) / 10.0  # Heuristic

        results.append(MatchingResult(
            atom_id=retrieval.atom_id,
            candidates=[
                ModuleCandidate(
                    module=module,
                    feature=info["feature"],
                    match_count=info["count"],
                    evidence=info["evidence"]
                )
                for module, info in scored
            ],
            confidence=min(confidence, 1.0)
        ))

        logger.info(
            "matching_completed",
            atom_id=retrieval.atom_id,
            candidate_count=len(scored)
        )

    return results
```

## Scoring

Candidates scored by:
1. **Frequency** — How many KB atoms mention this module
2. **Position** — If mentioned in first retrieval result (weighted higher)
3. **Similarity** — Using retrieval scores

## Knowledge Base Dependencies

Relies on KB atoms having `module` and `feature` fields:

```python
# KB atom example
atom = RequirementAtom(
    text="Sales orders with multi-level approval",
    module="Sales",
    feature="Approval workflows",
    country="US"
)
```

Seed from: `knowledge_bases/d365_fo/seed_data/`

## Error Handling

```python
# No similar atoms found
if not retrieval.similar_atoms:
    results.append(MatchingResult(
        atom_id=retrieval.atom_id,
        candidates=[],
        confidence=0.0
    ))
    logger.warning("matching_no_candidates", atom_id=retrieval.atom_id)
    continue

# No modules in KB atoms
if not any(a.module for a in retrieval.similar_atoms):
    results.append(MatchingResult(
        atom_id=retrieval.atom_id,
        candidates=[],
        confidence=0.0
    ))
```

## Testing

```python
@pytest.mark.asyncio
async def test_phase3_matching():
    retrieval = factories.make_retrieval_result(
        similar_atoms=[
            factories.make_atom(module="Sales", feature="Orders"),
            factories.make_atom(module="Sales", feature="Orders"),
            factories.make_atom(module="Inventory", feature="Stock"),
        ]
    )

    result = await phase3_matching([retrieval])

    assert len(result) == 1
    assert result[0].candidates[0].module == "Sales"  # Most frequent
    assert result[0].candidates[0].match_count == 2

@pytest.mark.asyncio
async def test_phase3_no_matches():
    retrieval = factories.make_retrieval_result(similar_atoms=[])
    result = await phase3_matching([retrieval])

    assert result[0].candidates == []
    assert result[0].confidence == 0.0
```

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — Node pattern
- [phase2_rag.md](phase2_rag.md) — Upstream: retrieval
- [phase4_classification.md](phase4_classification.md) — Downstream: classification
