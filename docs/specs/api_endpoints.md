# API Endpoints — REQFIT Frontend-Backend Contracts

**File location:** `api/routes/batches.py`, `api/routes/dynafit.py`

**Key principle:** Routes validate input → dispatch to Celery → return immediately. Zero business logic in routes.

---

## Endpoint Summary

| Method | Path | Auth | Request | Response | Status |
|--------|------|------|---------|----------|--------|
| POST | `/api/v1/upload` | None | multipart (file) | UploadResponse | 201 |
| POST | `/api/v1/d365_fo/dynafit/run` | None | RunRequest (JSON) | RunResponse | 202 |
| GET | `/api/v1/batches/{batch_id}` | None | - | BatchResponse | 200 |
| GET | `/api/v1/batches/{batch_id}/results` | None | - | BatchResultsResponse | 200 |
| GET | `/api/v1/batches/{batch_id}/review` | None | - | ReviewQueueResponse | 200 |
| POST | `/api/v1/batches/{batch_id}/review/{atom_id}` | None | ReviewOverride | ReviewAckResponse | 200 |
| GET | `/api/v1/batches/{batch_id}/export` | None | - | CSV file | 200 |
| WS | `/ws/progress/{batch_id}` | None | - | Event stream | 101 |

---

## Detailed Endpoints

### 1. POST /api/v1/upload (File Upload)

**Purpose:** Accept document, validate format, save to disk.

**Request:**
```
multipart/form-data:
  file: <binary>
  (optional) product: str = "d365_fo"
  (optional) country: str
  (optional) wave: int
```

**Response (201):**
```json
{
  "upload_id": "upl_a1b2c3d4",
  "filename": "requirements.pdf",
  "size_bytes": 245760,
  "detected_format": "PDF|DOCX|TXT",
  "status": "uploaded"
}
```

**Flow:** Save file → Run format detection (G1-lite) → Return immediately.

---

### 2. POST /api/v1/d365_fo/dynafit/run (Start Analysis)

**Purpose:** Queue batch processing pipeline.

**Request:**
```json
{
  "upload_id": "upl_a1b2c3d4",
  "config_overrides": {
    "fit_confidence_threshold": 0.85,
    "review_confidence_threshold": 0.60,
    "auto_approve_with_history": true
  }
}
```

**Response (202 — Accepted):**
```json
{
  "batch_id": "bat_abc123",
  "upload_id": "upl_a1b2c3d4",
  "status": "queued",
  "websocket_url": "/ws/progress/bat_abc123"
}
```

**Flow:** Validate upload exists → Create batch in PostgreSQL → Queue Celery task → Return.

---

### 3. GET /api/v1/batches/{batch_id} (Get Batch Status)

**Response (200):**
```json
{
  "batch_id": "bat_abc123",
  "upload_id": "upl_a1b2c3d4",
  "status": "queued|processing|awaiting_review|completed|failed",
  "phase": 1|2|3|4|5,
  "phase_name": "Ingestion|RAG|Matching|Classification|Validation",
  "result_count": 42,
  "flagged_count": 2,
  "created_at": "2024-03-28T10:00:00Z",
  "completed_at": null
}
```

---

### 4. GET /api/v1/batches/{batch_id}/results (Get Classifications)

**Response (200):**
```json
{
  "batch_id": "bat_abc123",
  "results": [
    {
      "atom_id": "REQ-001",
      "text": "Sales order workflow",
      "classification": "FIT|GAP|PARTIAL_FIT",
      "confidence": 0.95,
      "rationale": "Matches SAP Order Management",
      "matched_features": ["Order Management"],
      "evidence": {...}
    }
  ],
  "summary": {
    "total": 100,
    "fit": 65,
    "partial_fit": 25,
    "gap": 10
  }
}
```

**Status requirement:** Only available when batch.status != "processing"

---

### 5. GET /api/v1/batches/{batch_id}/review (Get Flagged Items — HITL)

**Response (200):**
```json
{
  "batch_id": "bat_abc123",
  "flagged": [
    {
      "atom_id": "REQ-042",
      "text": "Complex integration requirement",
      "ai_classification": "GAP",
      "confidence": 0.92,
      "flag_reason": "high_confidence_gap|low_score_fit|llm_schema_retry_exhausted"
    }
  ],
  "total_flagged": 2
}
```

**Status requirement:** batch.status == "awaiting_review"

---

### 6. POST /api/v1/batches/{batch_id}/review/{atom_id} (Submit Override)

**Request:**
```json
{
  "decision": "APPROVE|OVERRIDE",
  "override_classification": "FIT|GAP|PARTIAL_FIT",
  "reviewer": "user@company.com",
  "rationale": "Override reason"
}
```

**Response (200):**
```json
{
  "atom_id": "REQ-042",
  "decision_accepted": true,
  "timestamp": "2024-03-28T10:15:00Z"
}
```

**Flow:** Store override in PostgreSQL → Check if all flagged resolved → Resume graph if complete.

---

### 7. GET /api/v1/batches/{batch_id}/export (Export CSV)

**Response (200):** CSV file with columns:
```
atom_id, text, requirement_id, module, priority, classification,
confidence, matched_features, gap_type, dev_effort, configuration_steps
```

**Status requirement:** batch.status == "completed"

---

## WebSocket: /ws/progress/{batch_id}

**Events emitted (server → client):**

| Event | Payload | When |
|-------|---------|------|
| `phase_started` | `{phase: 1-5, phase_name: str}` | Phase begins |
| `atoms_extracted` | `{count: int}` | Phase 1 extracts requirements |
| `phase_completed` | `{phase: 1-5, result_count: int, latency_ms: int}` | Phase ends |
| `review_required` | `{flagged_count: int}` | Phase 5 hits checkpoint |
| `batch_completed` | `{status: str, summary: {...}, report_path: str}` | Batch done |
| `error` | `{phase: int, error: str, recoverable: bool}` | Failure occurs |

---

### 8. GET /api/v1/d365_fo/dynafit/batches (List Batches)

**Purpose:** Query historical batches by filters.

**Query Parameters:**
```
?country=DE              (optional)
?wave=3                  (optional)
?status=complete|failed  (optional)
?page=1&limit=10         (optional)
```

**Response (200):**
```json
{
  "batches": [
    {
      "batch_id": "bat_e5f6g7h8",
      "upload_filename": "requirements.pdf",
      "country": "DE",
      "wave": 3,
      "status": "completed|failed|awaiting_review",
      "summary": {"fit": 37, "partial_fit": 7, "gap": 6},
      "created_at": "2026-03-19T14:20:00Z",
      "completed_at": "2026-03-19T14:35:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 10,
    "total": 47
  }
}
```

---

## Error Responses

**Format (4xx, 5xx):**
```json
{
  "detail": "Human-readable error",
  "status": 400|404|409|500,
  "error_code": "BATCH_NOT_FOUND|INVALID_STATUS|CONFLICT",
  "timestamp": "2024-03-28T10:00:00Z"
}
```

**Common errors:**
- 404: Batch/upload not found
- 400: Batch status invalid for operation (e.g., GET /review when not awaiting_review)
- 409: Review already submitted for atom_id
- 500: Graph execution error (see phase logs)

---

## Batch Lifecycle States

```
uploaded → queued → processing → awaiting_review → completed
                                       ↓
                              (human decisions)
                                    ↓
                                completed
```

- **uploaded:** File accepted
- **queued:** Waiting for Celery worker
- **processing:** Graph executing phases
- **awaiting_review:** Sanity gate flagged items; HITL paused
- **completed:** All phases done, all reviews resolved
- **failed:** Unrecoverable error at any phase
