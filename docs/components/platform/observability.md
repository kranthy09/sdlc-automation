# Observability — Logging + Metrics

**What:** Structured JSON logging + Prometheus metrics.

**Where:** `platform/observability/`

---

## Logging

```python
from platform.observability import get_logger

logger = get_logger(__name__)

# Structured logs (JSON output)
logger.info("requirement_processed", req_id="REQ-001", confidence=0.92)
logger.warning("phase_slow", phase=2, duration_s=45.3)
logger.error("classification_failed", error="schema_mismatch", attempt=3)
```

## What Gets Logged Automatically

- **Correlation ID** — Added to every log automatically (from contextvars)
- **Timestamp** — ISO 8601
- **Level** — INFO, WARNING, ERROR, DEBUG
- **Module** — Which file/function
- **Custom fields** — Your data

## Usage Rules

1. **Always structured.** Pass fields as kwargs:
   ```python
   logger.info("batch_started", batch_id=batch_id, file_count=5)
   ```

2. **No f-strings in messages:**
   ```python
   # WRONG
   logger.info(f"Batch {batch_id} started")

   # RIGHT
   logger.info("batch_started", batch_id=batch_id)
   ```

3. **One log per event:**
   ```python
   logger.info("phase_completed", phase=1, atom_count=42, duration_s=12.5)
   ```

## Metrics

Auto-tracked at all platform boundaries:

```
# LLM calls
llm_tokens_input_total
llm_tokens_output_total
llm_requests_total
llm_errors_total

# Database
db_query_duration_seconds (histogram)
db_connection_pool_size (gauge)

# Vector store
retrieval_search_duration_seconds (histogram)
retrieval_results_count (counter)

# Redis
redis_publish_duration_seconds (histogram)
redis_subscribe_lag_seconds (gauge)
```

**Access Prometheus:**
```
http://localhost:9090
```

Query: `llm_tokens_input_total{model="claude-3-5-sonnet"}`

## When Adding Metrics

Don't. They're already tracked at platform layer boundaries (LLM, DB, Redis, Qdrant).

If you need a custom metric:
```python
from prometheus_client import Counter

my_counter = Counter("my_events_total", "Custom event counter")
my_counter.inc()
```

Register in `platform/observability/__init__.py`.

## Context Variables

Correlation ID is auto-propagated:

```python
from contextvars import get_context

context = get_context()
correlation_id = context.get("correlation_id")

# Every log in this coroutine will include it
logger.info("step1", step=1)
logger.info("step2", step=2)
```

Set at request entry (API layer):
```python
from platform.observability import set_context

@app.middleware("http")
async def add_context(request, call_next):
    correlation_id = request.headers.get("x-correlation-id", uuid4())
    set_context("correlation_id", correlation_id)
    return await call_next(request)
```

## Testing

Log assertions:
```python
def test_phase_logs_correctly(caplog):
    import logging
    caplog.set_level(logging.INFO)

    # Run code that logs
    logger.info("test_event", value=123)

    # Assert
    assert "test_event" in caplog.text
```

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — Logging examples in phase nodes
- `platform/observability/logger.py` — Logger implementation
- `platform/observability/metrics.py` — Metrics setup
