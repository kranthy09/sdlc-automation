# LLM Client — Claude API Wrapper

**What:** Centralized Claude API access with retry logic, structured output, cost tracking.

**Where:** `platform/llm/client.py`

**Use this:** Every LLM call in phase nodes goes through here.

---

## Core Function

```python
from platform.llm.client import classify

result = await classify(
    prompt=your_jinja2_rendered_template,
    output_schema=YourPydanticSchema,
    config=product_config
)
```

## What It Does

1. **Calls Claude** with your prompt
2. **Enforces structured output** via tool_use + Pydantic
3. **Retries on schema mismatch** (max 3 attempts)
4. **Tracks cost** (input tokens, output tokens, model name)
5. **Logs correlation ID** (auto-added by observability layer)

## When NOT to Use

❌ Don't import Anthropic directly
❌ Don't call Claude in a for-loop (batch at the node level)
❌ Don't hardcode `model="claude-3.5-sonnet"` — it reads from config

## Configuration

All settings from `.env`:

```
LLM_MODEL=claude-3-5-sonnet-20241022
LLM_MAX_RETRIES=3
LLM_TEMPERATURE=0
LLM_MAX_TOKENS=2048
```

Access in your node:
```python
from platform.config import get_settings
settings = get_settings()
model = settings.llm_model  # "claude-3-5-sonnet-20241022"
```

## Common Calls

**Classification (structured output):**
```python
result = await classify(
    prompt="Classify this requirement: {{ req }}",
    output_schema=ClassificationResult,
    config=config
)
# Returns: ClassificationResult instance
```

**Multi-step reasoning:**
```python
# Step 1: Extract reasoning
reasoning = await classify(
    prompt=...,
    output_schema=ReasoningSchema,
    config=config
)

# Step 2: Use reasoning for classification
final = await classify(
    prompt=f"Based on: {reasoning.thinking}. Classify...",
    output_schema=ClassificationResult,
    config=config
)
```

## Error Handling

```python
from platform.llm.client import LLMError

try:
    result = await classify(..., config=config)
except LLMError as e:
    logger.error("classification_failed", error=str(e))
    # Phase 4 node: set classification = REVIEW_REQUIRED
    return ClassificationResult(
        ...,
        classification="REVIEW_REQUIRED",
        rationale=f"LLM error: {e}"
    )
```

Retry logic is automatic (built-in to `classify()`). On 3rd failure, raises `LLMError`.

## Testing

**Golden fixtures (record once, replay always):**

```python
# In tests/fixtures/golden/phase4_classification.json
{
    "prompt": "Classify: Sales process",
    "response": {"classification": "FIT", "confidence": 0.95, ...}
}
```

**Mock for unit tests (no real LLM calls):**

```python
@patch("platform.llm.client.classify")
async def test_phase4_node(mock_classify):
    mock_classify.return_value = ClassificationResult(...)
    result = await phase4_node(input_data)
    assert result.classification == "FIT"
```

## Cost Tracking

Every call logs tokens used. Prometheus metrics auto-tracked:

```
llm_tokens_input_total
llm_tokens_output_total
llm_requests_total
llm_errors_total
```

No manual tracking needed.

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — How to call it in a node
- [CONFIG.md](config.md) — Configuration source
- `platform/llm/client.py` — Full implementation
