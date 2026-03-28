# API — Batch Endpoints

**File:** `api/routes/batches.py`

**Depends on:** `modules/dynafit/graph.py` (REQFIT graph)

---

## Endpoints

### POST /api/v1/batches (Create Batch)

**Request:** `multipart/form-data` with file binary

**Response (201):**
```json
{
  "batch_id": "batch_abc123",
  "status": "running",
  "phase": 1,
  "created_at": "2024-03-28T10:00:00Z"
}
```

**Flow:** Receive file → Create RawUpload → Queue Celery task → Return batch_id

---

### GET /api/v1/batches/{batch_id} (Get Status)

**Response (200):**
```json
{
  "batch_id": "batch_abc123",
  "status": "running|awaiting_review|completed|failed",
  "phase": 1-5,
  "phase_name": "Ingestion|RAG|Matching|Classification|Validation",
  "result_count": 42,
  "created_at": "2024-03-28T10:00:00Z",
  "completed_at": null
}
```

---

### GET /api/v1/batches/{batch_id}/results (Get Results)

**Response (200):**
```json
{
  "batch_id": "batch_abc123",
  "results": [
    {
      "atom_id": "REQ-001",
      "text": "Sales order workflow",
      "classification": "FIT|GAP|PARTIAL_FIT",
      "confidence": 0.95,
      "rationale": "...",
      "matched_features": ["Order Management"]
    }
  ],
  "fit_count": 30,
  "gap_count": 10,
  "review_count": 2
}
```

---

### GET /api/v1/batches/{batch_id}/review (Get Flagged Items — HITL)

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
      "flag_reason": "high_confidence_gap|low_score_fit|malformed_output"
    }
  ],
  "total_flagged": 2
}
```

**Status:** Only available when batch.status == "awaiting_review"

---

### POST /api/v1/batches/{batch_id}/review/{atom_id} (Submit Override — HITL)

**Request:**
```json
{
  "classification": "FIT|GAP|REVIEW_REQUIRED",
  "reviewer": "user@company.com",
  "override_classification": "FIT" (optional)
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

**Flow:** Validate status → Store override in DB → Check if all items reviewed → Resume graph if complete

---

### GET /api/v1/batches/{batch_id}/export (Export Results as CSV)

**Response (200):** CSV file with columns:
```
atom_id, text, req_id, module, priority, classification, confidence, rationale
```

**Status:** Only available when batch.status == "completed"

---

## WebSocket (Real-time Updates)

**Connect:**
```javascript
const socket = io("http://localhost:8000");
socket.emit("subscribe_batch", { batch_id: "batch_abc123" });
```

**Events emitted:**
- `phase_started`: {phase: 1, phase_name: "Ingestion"}
- `phase_completed`: {phase: 2, result_count: 42}
- `review_required`: {flagged_count: 2}
- `batch_completed`: {fit_count: 30, gap_count: 10, report_path: "..."}

**Implementation:** Graph nodes publish to Redis; Redis handler broadcasts to WebSocket room `batch_{batch_id}`.

---

## Error Responses

All endpoints return standard format (4xx, 5xx):
```json
{
  "detail": "Batch not found",
  "status": 404,
  "timestamp": "2024-03-28T10:00:00Z"
}
```

**Common errors:**
- 404: Batch not found
- 400: Batch status invalid for operation (e.g., GET /review when not awaiting_review)
- 409: Review already submitted for atom_id
- 500: Graph execution error (see phase logs)

---

## See Also

- [graph.md](../modules/graph.md) — Graph execution + checkpoints
- [phase5_validation.md](../modules/phase5_validation.md) — HITL flow + flagging logic
- [PATTERNS.md](../../guides/PATTERNS.md) — API patterns
