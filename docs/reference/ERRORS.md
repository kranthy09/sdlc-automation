# Error Codes and Handling

When you see these errors, here's what they mean and what to do.

---

## Setup / Environment

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: No module named 'platform'` | Venv not activated or deps not installed | Run `source .venv/bin/activate && pip install -e .` |
| `ImportError: cannot import name X from platform.Y` | Import boundary violation | Check `make validate-contracts` output. Ensure layer hierarchy. |
| `POSTGRES_DSN not found in environment` | `.env` missing or incomplete | Copy `.env.example` to `.env` and fill in credentials |
| `Connection refused to localhost:5432` | PostgreSQL not running | Run `docker-compose up -d` |

---

## Validation / Type Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `ValidationError: field required` | Schema missing required field | Check Pydantic model definition. Input must match schema exactly. |
| `mypy error: Argument 1 has incompatible type` | Type mismatch | Annotate function arguments and return types. Run `make lint`. |
| `strict=True validation failed` | Input doesn't match schema precisely | Convert/validate input BEFORE passing to phase node. |

---

## File Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `UnsupportedFormatError: File format not recognized` | File is not PDF, DOCX, or TXT | Only PDF, DOCX, TXT supported. Check `DocumentFormat` enum. |
| `FileValidationError: File exceeds 50 MB` | File too large | Guardrail G1-lite rejects > 50 MB. User must split document. |
| `InjectionScanResult.severity == "BLOCK"` | File contains prompt injection patterns | Guardrail G3-lite detected malicious content. Block user and audit. |

---

## LLM / Retrieval

| Error | Cause | Fix |
|-------|-------|-----|
| `LLMError: API rate limited` | Claude API quota exceeded | Backoff and retry. `platform/llm/client.py` handles retries automatically (max 3). |
| `LLMError: Structured output validation failed after 3 retries` | LLM output doesn't match schema | Phase 4 node sets `classification=REVIEW_REQUIRED`. Don't retry again. |
| `RetrievalError: Qdrant connection timeout` | Vector store unreachable | Check `docker ps`. Restart: `docker-compose restart qdrant`. |
| `BM25Error: No documents in index` | Knowledge base empty | Seed KB: `python -m modules.dynafit.load_kb`. Check `knowledge_bases/d365_fo/`. |

---

## Guardrails

| Error | Cause | Fix |
|-------|-------|-----|
| `GuardrailError: [\'reason1\', \'reason2\']` | Guardrail blocked input | Check guardrail severity. G1-lite, G3-lite, etc. are in phase node. |
| `ClassificationResult.route == REVIEW_REQUIRED` | LLM output unparseable | Manual review at Phase 5. HITL will show it. |

---

## Database / Storage

| Error | Cause | Fix |
|-------|-------|-----|
| `psycopg.OperationalError: connection failed` | PostgreSQL down | Run `docker-compose up -d postgres`. Check `POSTGRES_DSN` in `.env`. |
| `RedisConnectionError: Connection refused` | Redis down | Run `docker-compose up -d redis`. |
| `CheckpointError: Failed to save state` | LangGraph checkpoint write failed | DB full or permissions issue. Check logs: `docker-compose logs postgres`. |

---

## API / Celery

| Error | Cause | Fix |
|-------|-------|-----|
| `HTTPException: 400 Bad Request` | Invalid request schema | Check `api/routes/`. Body must match Pydantic model. |
| `Task failed: celery.exceptions.Retry` | Async task timed out or crashed | Check task logs. Long batches may need `task_timeout` increased in config. |
| `WebSocket disconnect` | UI disconnected during phase execution | UI auto-reconnects. Check network. If batch crashed, check `api/tasks/` logs. |

---

## CI / Testing

| Error | Cause | Fix |
|-------|-------|-----|
| `make validate-contracts failed` | Import boundary violated | Check output. Move file to correct layer or change imports. |
| `make lint failed` | Ruff or mypy error | Run `make format` to auto-fix Ruff. Manual fixes: add type hints, imports. |
| `make test failed` | Test assertion or integration failure | Check test output. If integation test: verify services running (`docker-compose ps`). |

---

## Debugging

```bash
# See what's happening
docker-compose logs -f postgres    # DB logs
docker-compose logs -f redis       # Redis logs
docker-compose logs -f qdrant      # Vector store logs

# Check module state
python -c "from modules.dynafit.graph import graph; print(graph.nodes.keys())"

# Run single test
pytest tests/unit/test_phase1.py::test_ingestion -v

# Full validation
make validate-contracts && make lint && make test
```
