# Schemas — Data Contracts

**What:** Pydantic v2 models that define boundaries between layers.

**Where:** `platform/schemas/`

**When to use:** Every layer boundary must validate input and output against a schema.

---

## What Goes Here

Every `.py` file in `platform/schemas/` exports one or more Pydantic models.

```python
# Example: platform/schemas/requirements.py
from pydantic import BaseModel, Field

class RequirementAtom(BaseModel):
    id: str
    text: str
    priority: str | None = None

    model_config = ConfigDict(frozen=True)  # Immutable
```

## Rules

1. **All fields typed** — No `Any`, no untyped dicts
2. **Frozen models** — Use `frozen=True` for immutable data
3. **Validation at boundaries** — Call `model_validate()` for incoming data
4. **JSON serializable** — All fields must serialize to JSON (for API responses, events)
5. **No circular imports** — Keep import graph clean

## When Adding a New Schema

1. **Identify its layer.** Does it flow between layers?
   - If yes → add to `platform/schemas/`
   - If module-specific → add to module's `schemas.py`

2. **Write type hints first.** Then validate in code.

3. **Add docstring** with example:
   ```python
   class MySchema(BaseModel):
       """Represents a fitment decision.

       Example:
           MySchema(id="REQ-001", classification="FIT")
       """
       id: str
       classification: str
   ```

4. **Use in code:**
   ```python
   # Input validation
   data = MySchema.model_validate(raw_data)

   # Output serialization
   return data.model_dump(mode="json")
   ```

## Files

| File | What |
|------|------|
| `batches.py` | Batch, AtomizedBatch, ValidatedFitmentBatch |
| `requirements.py` | RequirementAtom |
| `fitment.py` | ClassificationResult, FitmentMatch |
| `retrieval.py` | RetrievalResult, RetrievedAtom |
| `guardrails.py` | GuardrailResult, FileValidationResult, InjectionScanResult |
| `events.py` | PhaseStartEvent, PhaseCompleteEvent |
| `documents.py` | DocumentFormat, DetectedFormat |
| `upload.py` | RawUpload |

## Common Patterns

**Optional fields:**
```python
req_id: str | None = None
```

**With defaults:**
```python
priority: str = Field(default="Medium")
```

**With validation:**
```python
confidence: float = Field(ge=0.0, le=1.0)
```

**Nested models:**
```python
class Batch(BaseModel):
    atoms: list[RequirementAtom]
```

**Enum fields:**
```python
from enum import Enum
class Classification(str, Enum):
    FIT = "FIT"
    GAP = "GAP"

classification: Classification
```

## Testing Schemas

```python
def test_requirement_atom_validation():
    # Valid input
    atom = RequirementAtom.model_validate({"id": "A1", "text": "..."})
    assert atom.id == "A1"

    # Invalid input raises ValidationError
    with pytest.raises(ValidationError):
        RequirementAtom.model_validate({"text": "..."})  # missing id
```

## See Also

- [SCHEMAS.md](../../reference/SCHEMAS.md) — Key schema reference
- `platform/schemas/__init__.py` — All exported models
