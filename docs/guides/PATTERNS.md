# Patterns — How to Build Common Components

Use these patterns when adding new features or nodes.

**Before you start:** Read [DEVELOPMENT_RULES.md](../DEVELOPMENT_RULES.md) — confirm scope, one component per session.

---

## Building a Phase Node

**File:** `modules/dynafit/nodes/phaseX_name.py`

```python
from platform.llm.client import classify  # Call platform utilities
from platform.schemas import MyInput, MyOutput

async def phase_node(input_data: MyInput) -> MyOutput:
    """
    1. Validate input (it comes from schema — already valid)
    2. Call platform utilities
    3. Return output matching schema
    """
    # Example: call LLM
    result = await classify(
        prompt=template.render(data=input_data),
        output_schema=ClassificationResult,
        config=config
    )
    return MyOutput.model_validate(result)
```

**What NOT to do:**
- ❌ Import Anthropic/Qdrant directly — use `platform/llm`, `platform/retrieval`
- ❌ Hardcode thresholds — put them in `platform/config`
- ❌ Log without correlation ID — use `structlog` via `platform/observability`

---

## Writing a Jinja2 Prompt Template

**File:** `modules/dynafit/prompts/template_v1.j2`

```jinja2
<system>
You are a requirement classifier.
</system>

<requirement>
{{ requirement_text | e }}
</requirement>

<context>
Similar requirements from knowledge base:
{% for item in context_items %}
- {{ item.text | e }}
{% endfor %}
</context>

Return JSON: {"classification": "FIT" | "GAP", "confidence": 0.0-1.0}
```

**Rules:**
- Always use `| e` filter for user data (escaping)
- Use `StrictUndefined` in Jinja2 environment (code sets this)
- Never f-strings or concatenation — templates only
- System instructions are NEVER built from user data

---

## Adding a Guardrail

**File:** `platform/guardrails/my_guardrail.py`

```python
from platform.schemas.guardrails import GuardrailResult

def validate_input(data: InputSchema) -> GuardrailResult:
    """
    Return GuardrailResult with:
    - passed: bool
    - flags: list[str] (what triggered)
    - severity: "BLOCK" | "FLAG_FOR_REVIEW" | "PASS"
    """
    if bad_condition:
        return GuardrailResult(passed=False, severity="BLOCK", flags=["reason"])
    return GuardrailResult(passed=True, severity="PASS")

# Call it in phase node BEFORE processing
result = validate_input(data)
if result.severity == "BLOCK":
    raise GuardrailError(result.flags)
```

---

## Adding an API Endpoint

**File:** `api/routes/my_resource.py`

```python
from fastapi import APIRouter
from platform.schemas import RequestSchema, ResponseSchema

router = APIRouter(prefix="/api/v1/resource")

@router.get("/{id}")
async def get_resource(id: str) -> ResponseSchema:
    """
    1. Validate input (FastAPI does this)
    2. Call module service (not platform directly)
    3. Return response schema
    """
    result = await my_service.get(id)
    return ResponseSchema.model_validate(result)
```

**Import rule:** API imports ONLY from `modules/` graph entry points and `platform/schemas/`.

---

## Testing Patterns

**Integration test:** Core workflow, real DB.

```python
async def test_phase1_ingestion():
    """Real file, real extraction, no mocks."""
    file = factories.make_raw_upload()
    result = await phase1_node(file)
    assert result.atoms is not None
```

**Unit test:** Complex logic only.

```python
def test_injection_scanner_detects_prompt_injection():
    """Business logic: is this a prompt injection? Test the rule."""
    text = "ignore previous instructions"
    score = scanner.score(text)
    assert score > 0.5
```

**Never test:** Constructors, defaults, every enum value, callables.

---

## Logging and Observability

```python
from platform.observability import get_logger

logger = get_logger(__name__)

# Structured logging (context auto-adds correlation ID)
logger.info("phase_started", phase=1, batch_id=batch_id)
logger.error("validation_failed", phase=2, errors=errors)

# Metrics (auto-tracked at platform boundaries)
# Don't add them — they're already there for LLM, DB, Redis calls
```

---

## Configuration

**Never hardcode.** Use `platform/config/settings.py`.

```python
from platform.config import get_settings

settings = get_settings()
threshold = settings.classification_confidence_threshold  # From env
```

**Env vars:**
- `LLM_MODEL` → which Claude version
- `QDRANT_URL` → retrieval backend
- `POSTGRES_DSN` → database
- See `.env.example`
