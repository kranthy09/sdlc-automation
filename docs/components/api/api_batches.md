# API — Batch Endpoints

**What:** FastAPI routes for batch operations (create, poll, review, export).

**File:** `api/routes/batches.py`

**Depends on:** `modules/dynafit/graph.py` (REQFIT graph)

---

## Endpoints

### 1. Create Batch

```
POST /api/v1/batches
Content-Type: multipart/form-data

file: <binary file>
```

**Response (201):**
```json
{
  "batch_id": "batch_abc123",
  "status": "running",
  "phase": 1,
  "created_at": "2024-03-28T10:00:00Z"
}
```

**Implementation:**
```python
@router.post("/api/v1/batches", response_model=BatchResponse)
async def create_batch(file: UploadFile):
    """
    1. Receive file
    2. Create RawUpload
    3. Queue graph execution in Celery
    4. Return batch_id
    """
    batch_id = str(uuid4())

    upload = RawUpload(
        filename=file.filename,
        file_bytes=await file.read(),
        upload_id=batch_id
    )

    # Queue long-running task
    task = execute_graph.delay(batch_id, upload)

    return BatchResponse(
        batch_id=batch_id,
        status="running",
        phase=1,
        created_at=datetime.utcnow()
    )
```

### 2. Get Batch Status

```
GET /api/v1/batches/{batch_id}
```

**Response (200):**
```json
{
  "batch_id": "batch_abc123",
  "status": "running" | "awaiting_review" | "completed" | "failed",
  "phase": 1-5 | null,
  "phase_name": "Ingestion" | "RAG" | ... | null,
  "result_count": 42,
  "created_at": "2024-03-28T10:00:00Z",
  "completed_at": null
}
```

**Implementation:**
```python
@router.get("/api/v1/batches/{batch_id}", response_model=BatchResponse)
async def get_batch(batch_id: str):
    """Get current batch status."""
    batch = await db.get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    return BatchResponse.model_validate(batch)
```

### 3. Get Batch Results

```
GET /api/v1/batches/{batch_id}/results
```

**Response (200):**
```json
{
  "batch_id": "batch_abc123",
  "results": [
    {
      "atom_id": "REQ-001",
      "text": "Sales order workflow",
      "classification": "FIT",
      "confidence": 0.95,
      "rationale": "...",
      "matched_features": ["Order Management"]
    },
    ...
  ],
  "fit_count": 30,
  "gap_count": 10,
  "review_count": 2
}
```

**Implementation:**
```python
@router.get("/api/v1/batches/{batch_id}/results", response_model=BatchResultsResponse)
async def get_batch_results(batch_id: str):
    """Get classification results."""
    batch = await db.get_batch_results(batch_id)
    if not batch:
        raise HTTPException(404)
    return BatchResultsResponse.model_validate(batch)
```

### 4. Get Flagged Items (HITL)

```
GET /api/v1/batches/{batch_id}/review
```

**Response (200):**
```json
{
  "batch_id": "batch_abc123",
  "flagged": [
    {
      "atom_id": "REQ-042",
      "text": "...",
      "current_classification": "GAP",
      "confidence": 0.92,
      "flag_reason": "high_confidence_gap"
    }
  ],
  "total_flagged": 2
}
```

**Implementation:**
```python
@router.get("/api/v1/batches/{batch_id}/review")
async def get_flagged_items(batch_id: str):
    """Get items waiting for human review."""
    batch = await db.get_batch(batch_id)
    if batch.status != "awaiting_review":
        raise HTTPException(400, "Batch not awaiting review")
    return {
        "batch_id": batch_id,
        "flagged": batch.flagged_for_review,
        "total_flagged": len(batch.flagged_for_review)
    }
```

### 5. Submit Human Review (HITL)

```
POST /api/v1/batches/{batch_id}/review/{atom_id}
Content-Type: application/json

{
  "classification": "FIT" | "GAP" | "REVIEW_REQUIRED"
}
```

**Response (200):**
```json
{
  "atom_id": "REQ-042",
  "override_accepted": true,
  "timestamp": "2024-03-28T10:15:00Z"
}
```

**Implementation:**
```python
@router.post("/api/v1/batches/{batch_id}/review/{atom_id}")
async def submit_review(batch_id: str, atom_id: str, body: ReviewOverride):
    """Store human override and resume graph."""
    # 1. Validate
    batch = await db.get_batch(batch_id)
    if batch.status != "awaiting_review":
        raise HTTPException(400, "Not awaiting review")

    # 2. Store override
    await db.store_override(batch_id, atom_id, body.classification)

    # 3. Check if all flagged items reviewed
    remaining = await db.get_remaining_flagged(batch_id)
    if not remaining:
        # 4. Resume graph
        await graph.ainvoke_resume(
            batch_id,
            config={"configurable": {"thread_id": batch_id}}
        )

    return {"atom_id": atom_id, "override_accepted": True}
```

### 6. Export Results (CSV)

```
GET /api/v1/batches/{batch_id}/export
```

**Response (200 with CSV):**
```
atom_id,text,req_id,module,priority,classification,confidence,rationale
REQ-001,Sales order workflow,SO-001,Sales,Must,FIT,0.95,...
...
```

**Implementation:**
```python
@router.get("/api/v1/batches/{batch_id}/export")
async def export_batch(batch_id: str):
    """Export results as CSV."""
    batch = await db.get_batch_results(batch_id)
    if batch.status != "completed":
        raise HTTPException(400, "Batch not completed")

    csv_data = csv_export(batch.results)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=batch_{batch_id}.csv"}
    )
```

## Error Responses

All endpoints return standard error format:

```json
{
  "detail": "Batch not found",
  "status": 404,
  "timestamp": "2024-03-28T10:00:00Z"
}
```

## WebSocket (Real-time Updates)

**Connect:**
```javascript
const socket = io("http://localhost:8000");
socket.emit("subscribe_batch", { batch_id: "batch_abc123" });
```

**Receive events:**
```javascript
socket.on("phase_started", (data) => {
    console.log(`Phase ${data.phase} started`);
});

socket.on("phase_completed", (data) => {
    console.log(`Phase ${data.phase} done. ${data.result_count} atoms processed`);
});

socket.on("review_required", (data) => {
    console.log(`${data.flagged_count} items need review`);
    // Show review UI
});

socket.on("batch_completed", (data) => {
    console.log(`Done! ${data.fit_count} FIT, ${data.gap_count} GAP`);
});
```

**Implementation (async event loop):**
```python
@sio.event
async def subscribe_batch(sid, data):
    batch_id = data["batch_id"]
    sio.enter_room(sid, f"batch_{batch_id}")

# In graph nodes, publish via Redis:
await redis.publish(
    f"batch_{batch_id}:events",
    json.dumps({"event": "phase_completed", "phase": 2})
)

# Redis sub handler publishes to WebSocket room:
@redis.sub.listener()
async def on_event(msg):
    event = json.loads(msg["data"])
    await sio.emit("phase_completed", event, room=f"batch_{event['batch_id']}")
```

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — API patterns
- [graph.md](../modules/graph.md) — Graph execution
- [phase5_validation.md](../modules/phase5_validation.md) — HITL flow
