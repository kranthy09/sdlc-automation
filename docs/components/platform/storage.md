# Storage — PostgreSQL + Redis + LangGraph Checkpoints

**What:** Persistent state storage and pub/sub messaging.

**Where:** `platform/storage/`

---

## PostgreSQL (State)

**What:** Stores batches, atoms, results, human reviews.

**Setup:**
```bash
docker-compose up -d postgres
# DSN from .env: postgresql://user:pass@localhost:5432/enterprise_ai
```

**Access in code:**
```python
from platform.storage import get_db

async with get_db() as db:
    batch = await db.query(Batch).where(Batch.id == batch_id).first()
```

**LangGraph checkpoints:**
```python
from platform.storage import PostgresStore

store = PostgresStore(
    connection_string=settings.postgres_dsn,
    namespace="dynafit_graph"
)
graph = StateGraph(...).compile(checkpointer=store)
```

LangGraph auto-saves state after each phase. On `interrupt()` (Phase 5 HITL), state persists.

## Redis (Pub/Sub)

**What:** Real-time event broadcasting.

**Setup:**
```bash
docker-compose up -d redis
# URL from .env: redis://localhost:6379
```

**Publish events:**
```python
from platform.storage import get_redis

redis = await get_redis()
await redis.publish("phase_events", json.dumps({
    "batch_id": batch_id,
    "phase": 1,
    "status": "started"
}))
```

**Subscribe in UI (WebSocket):**
```javascript
// ui/src/hooks/usePhaseSubscription.ts
const socket = io("http://localhost:8000");
socket.on("phase_started", (data) => {
    console.log(`Phase ${data.phase} started for batch ${data.batch_id}`);
});
```

## Migrations

**Run once after `docker-compose up`:**
```bash
python -m platform.storage.migrations
# Creates tables: batches, atoms, results, human_reviews, checkpoints
```

**Add a new table:**
1. Create migration file: `platform/storage/migrations/001_add_my_table.py`
2. Run: `python -m platform.storage.migrations`

## Testing

**Use in-memory DB for unit tests:**
```python
@pytest.fixture
async def test_db():
    # Returns in-memory SQLite (no docker needed)
    return await create_in_memory_db()

async def test_batch_storage(test_db):
    batch = Batch(id="B1", status="running")
    await test_db.save(batch)
    assert await test_db.get_batch("B1") is not None
```

**Integration tests use real PostgreSQL:**
```python
@pytest.mark.integration
async def test_batch_with_real_db():
    # Requires: docker-compose up postgres
    batch = Batch(...)
    await db.save(batch)
    # ... verify
```

## Error Handling

```python
from platform.storage import DatabaseError, ConnectionError

try:
    await db.save(batch)
except DatabaseError as e:
    logger.error("db_write_failed", batch_id=batch.id)
except ConnectionError:
    logger.error("db_connection_lost")
    # Retry or fail gracefully
```

## Metrics

Auto-tracked:
```
db_query_duration_seconds
db_connection_pool_size
redis_publish_duration_seconds
redis_subscribe_lag_seconds
```

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — How to query in nodes
- `platform/storage/postgres.py` — Database implementation
- `platform/storage/redis_pub.py` — Pub/sub implementation
