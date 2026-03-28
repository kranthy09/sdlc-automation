# Phase 4 — Classification

**What:** Use LLM to classify each requirement as FIT, GAP, or REVIEW_REQUIRED.

**File:** `modules/dynafit/nodes/phase4_classification.py`

**Input:** `list[MatchingResult]` from Phase 3

**Output:** `list[ClassificationResult]` — FIT/GAP per requirement

---

## What It Does

For each requirement + candidate modules:
1. Render Jinja2 prompt template with context (similar atoms, candidates)
2. Call Claude LLM with structured output schema
3. Parse response → ClassificationResult
4. Handle schema mismatches (retry or set to REVIEW_REQUIRED)
5. Apply guardrails (G8 prompt firewall, G9 output schema)

## Output Schema

```python
class ClassificationResult(BaseModel):
    atom_id: str
    classification: "FIT" | "GAP" | "REVIEW_REQUIRED"
    confidence: float (0.0-1.0)
    rationale: str  # Why FIT or GAP
    matched_features: list[str] | None  # If FIT, which features
    route: "LLM_SUCCESS" | "LLM_SCHEMA_RETRY_EXHAUSTED" | "DIRECT_BLOCK"
```

## Implementation Pattern

```python
async def phase4_classification(
    matching_results: list[MatchingResult]
) -> list[ClassificationResult]:
    """
    For each MatchingResult:
      1. Load prompt template (G8: firewall check)
      2. Render with context
      3. Call LLM (G9: strict schema validation)
      4. Return result or REVIEW_REQUIRED on failure
    """

    results = []
    for matching in matching_results:
        # 1. Load template (G8 firewall)
        template = load_jinja_template("classification_v1.j2")
        # Checks: autoescape=True, StrictUndefined, allowed templates only

        # 2. Render
        prompt = template.render(
            requirement_text=atom.text,  # Escaped by | e filter
            similar_requirements=[r.text for r in matching.candidates],
            modules=[c.module for c in matching.candidates]
        )

        # 3. Call LLM
        try:
            result = await classify(
                prompt=prompt,
                output_schema=ClassificationResult,
                config=settings
            )
            result.route = "LLM_SUCCESS"
        except LLMError as e:
            logger.error("classification_llm_error", atom_id=matching.atom_id)
            result = ClassificationResult(
                atom_id=matching.atom_id,
                classification="REVIEW_REQUIRED",
                confidence=0.0,
                rationale=f"LLM error: {e}",
                matched_features=None,
                route="LLM_SCHEMA_RETRY_EXHAUSTED"
            )

        results.append(result)
        logger.info(
            "classification_completed",
            atom_id=matching.atom_id,
            classification=result.classification,
            confidence=result.confidence
        )

    return results
```

## Prompt Template

File: `modules/dynafit/prompts/classification_v1.j2`

```jinja2
<system>
You are a requirements classification expert. Classify each requirement
as FIT (D365 supports it), GAP (D365 doesn't support it), or
REVIEW_REQUIRED (uncertain).

Return JSON with classification, confidence (0.0-1.0), and rationale.
</system>

<requirement>
{{ requirement_text | e }}
</requirement>

<similar_requirements>
These similar requirements were found in the knowledge base:
{% for req in similar_requirements %}
- {{ req | e }}
{% endfor %}
</similar_requirements>

<candidate_modules>
These D365 modules might apply:
{% for module in modules %}
- {{ module | e }}
{% endfor %}
</candidate_modules>

Classify this requirement: FIT, GAP, or REVIEW_REQUIRED?
```

**Rules:**
- Always use `| e` filter (escape user data)
- Never f-strings or concatenation
- System instructions are NEVER from user data
- Environment has `autoescape=True`, `StrictUndefined`

## Guardrails

**G8 (Prompt Firewall):**
- Template files hardcoded: `classification_v1.j2`, `rationale_v1.j2`
- User data only in `{{ ... | e }}` slots
- Environment: `autoescape=True`, `StrictUndefined`

**G9 (Output Schema):**
- LLM output validated with `ClassificationResult` schema (strict mode)
- On validation error → retry (up to 3 times)
- On exhaustion → `classification=REVIEW_REQUIRED`

## Error Handling

```python
# Schema mismatch after retries
if result.route == "LLM_SCHEMA_RETRY_EXHAUSTED":
    # Phase 5 will flag for human review
    logger.warning("classification_review_required", atom_id=matching.atom_id)

# LLM timeout/error
except LLMError:
    # Set to REVIEW_REQUIRED, continue batch
    result = ClassificationResult(..., classification="REVIEW_REQUIRED")

# No matching candidates
if not matching.candidates:
    result = ClassificationResult(
        ...,
        classification="GAP",
        rationale="No matching D365 modules found"
    )
```

## Testing

```python
@pytest.mark.asyncio
async def test_phase4_classifies_fit():
    matching = factories.make_matching_result(
        candidates=[factories.make_module_candidate(module="Sales")]
    )
    with patch("platform.llm.client.classify") as mock:
        mock.return_value = ClassificationResult(
            atom_id="A1",
            classification="FIT",
            confidence=0.92,
            rationale="Sales module supports orders",
            matched_features=["Order Management"],
            route="LLM_SUCCESS"
        )
        result = await phase4_classification([matching])
        assert result[0].classification == "FIT"

@pytest.mark.asyncio
async def test_phase4_review_required_on_error():
    matching = factories.make_matching_result()
    with patch("platform.llm.client.classify") as mock:
        mock.side_effect = LLMError("Schema validation failed 3 times")
        result = await phase4_classification([matching])
        assert result[0].classification == "REVIEW_REQUIRED"
        assert result[0].route == "LLM_SCHEMA_RETRY_EXHAUSTED"
```

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — Node and prompt patterns
- [llm_client.md](../platform/llm_client.md) — Structured output, retry logic
- [guardrails.md](../platform/guardrails.md) — G8, G9 details
- `modules/dynafit/prompts/` — Template examples
