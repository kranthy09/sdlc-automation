# DYNAFIT — Frontend-Backend Interaction Specification

> **When to read this file:** Layer 4 of the build order (Week 6 in TDD_IMPLEMENTATION_GUIDE.md).
> The AI pipeline (Layers 0–3) must be complete and tested before building anything in this file.
>
> **This file covers everything the user sees and touches** — upload, progress, results, review, export.
> The DYNAFIT_IMPLEMENTATION_SPEC.md covers the AI pipeline. This file covers how the frontend
> drives that pipeline and what gets returned.
>
> **API rules (enforced by validate_contracts.py):**
> Routes validate input → dispatch to Celery → return immediately. Zero business logic in routes.
> If logic appears in a route, it moves to `modules/` or `platform/` before the PR merges.

---

## ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────┐
│  React + Vite + TanStack Query + Tailwind                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ Upload   │ │ Progress │ │ Results  │ │ Review   │       │
│  │ Page     │ │ Page     │ │ Table    │ │ Queue    │       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
│       │ REST        │ WS         │ REST        │ REST+WS    │
└───────┼─────────────┼────────────┼─────────────┼────────────┘
        │             │            │             │
┌───────▼─────────────▼────────────▼─────────────▼────────────┐
│  FastAPI (api/)                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │ POST /upload │ │ WS /progress │ │ GET /results │         │
│  │ POST /run    │ │ (real-time)  │ │ POST /review │         │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘         │
│         │                │                │                  │
│  ┌──────▼────────────────▼────────────────▼───────┐         │
│  │  Celery Worker (background)                     │         │
│  │  ┌─────────────────────────────────────────┐    │         │
│  │  │  LangGraph (DYNAFIT 5-phase pipeline)   │    │         │
│  │  │  State checkpointed to PostgreSQL        │    │         │
│  │  │  Progress emitted to Redis pubsub        │    │         │
│  │  └─────────────────────────────────────────┘    │         │
│  └─────────────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────────────┘
        │                │                │
   PostgreSQL         Qdrant           Redis
   (audit, state)   (vectors)     (queue, pubsub)
```

**The key principle:** The React frontend NEVER talks to LangGraph directly. It talks to FastAPI. FastAPI dispatches work to Celery. Celery runs the LangGraph pipeline. Progress flows back through Redis pub/sub → WebSocket → React.

---

## API ENDPOINTS (FastAPI)

### 1. File Upload

```
POST /api/v1/upload
Content-Type: multipart/form-data

Body:
  file: <binary>          # Excel, Word, PDF
  product: "d365_fo"      # product context
  country: "DE"           # legal entity
  wave: 3                 # wave number

Response 201:
{
  "upload_id": "upl_a1b2c3d4",
  "filename": "DE_AP_Requirements_Wave3.xlsx",
  "size_bytes": 245760,
  "detected_format": "XLSX",
  "status": "uploaded"
}
```

**What happens server-side:**
1. FastAPI receives multipart file
2. Saves to `/data/uploads/{upload_id}/{filename}`
3. Runs format detection (Phase 1, Step 1, Sub-step A) synchronously — fast, <100ms
4. Returns immediately. No processing yet.

### 2. Start Analysis

```
POST /api/v1/d365_fo/dynafit/run
Content-Type: application/json

Body:
{
  "upload_id": "upl_a1b2c3d4",
  "config_overrides": {           # optional
    "fit_confidence_threshold": 0.85,
    "auto_approve_with_history": true
  }
}

Response 202:
{
  "batch_id": "bat_e5f6g7h8",
  "upload_id": "upl_a1b2c3d4",
  "status": "queued",
  "websocket_url": "/api/v1/ws/progress/bat_e5f6g7h8"
}
```

**What happens server-side:**
1. FastAPI creates a `batch` record in PostgreSQL (status=QUEUED)
2. Dispatches Celery task: `run_dynafit_pipeline.delay(batch_id, upload_id, config)`
3. Returns 202 Accepted immediately with `batch_id` and WebSocket URL
4. Frontend opens WebSocket to track progress

### 3. Real-Time Progress (WebSocket)

```
WS /api/v1/ws/progress/{batch_id}
```

**Server sends these message types:**

```jsonc
// Phase started
{
  "type": "phase_start",
  "phase": 1,
  "phase_name": "Ingestion",
  "total_phases": 5,
  "timestamp": "2026-03-19T14:22:00Z"
}

// Step progress within a phase
{
  "type": "step_progress",
  "phase": 1,
  "step": "Document Parser",
  "sub_step": "Header Map",
  "progress_pct": 75,         // 0-100 within this phase
  "items_processed": 38,
  "items_total": 50,
  "timestamp": "2026-03-19T14:22:05Z"
}

// Phase completed
{
  "type": "phase_complete",
  "phase": 1,
  "phase_name": "Ingestion",
  "atoms_produced": 53,
  "atoms_validated": 50,
  "atoms_flagged": 2,
  "atoms_rejected": 1,
  "latency_ms": 4200,
  "timestamp": "2026-03-19T14:22:12Z"
}

// Classification result (streamed one-by-one during Phase 4)
{
  "type": "classification",
  "atom_id": "REQ-AP-041",
  "requirement_text": "Three-way matching for AP invoices",
  "classification": "FIT",
  "confidence": 0.94,
  "module": "AccountsPayable",
  "rationale": "D365 standard AP module supports three-way matching natively."
}

// Pipeline paused for human review (Phase 5)
{
  "type": "review_required",
  "batch_id": "bat_e5f6g7h8",
  "review_items": 5,
  "reasons": {
    "low_confidence": 3,
    "conflicts": 1,
    "anomalies": 1
  },
  "review_url": "/review/bat_e5f6g7h8"
}

// Pipeline complete
{
  "type": "complete",
  "batch_id": "bat_e5f6g7h8",
  "summary": {
    "total": 50,
    "fit": 37,
    "partial_fit": 7,
    "gap": 6
  },
  "report_url": "/api/v1/d365_fo/dynafit/bat_e5f6g7h8/report",
  "latency_total_ms": 120000
}

// Error
{
  "type": "error",
  "phase": 2,
  "message": "Qdrant connection timeout after 5s",
  "recoverable": true,
  "retry_at": "2026-03-19T14:23:00Z"
}
```

**How progress flows internally:**
1. Each LangGraph node (phase), after processing each atom, publishes to Redis: `PUBLISH progress:{batch_id} {json_message}`
2. FastAPI WebSocket handler subscribes: `SUBSCRIBE progress:{batch_id}`
3. On each Redis message → forward to connected WebSocket client
4. If WebSocket disconnects, no data lost — client reconnects and fetches current state via REST

### 4. Get Results

```
GET /api/v1/d365_fo/dynafit/{batch_id}/results
Query params:
  ?classification=FIT          # filter
  ?module=AccountsPayable      # filter
  ?sort=confidence             # sort field
  ?order=desc                  # sort direction
  ?page=1&limit=25             # pagination

Response 200:
{
  "batch_id": "bat_e5f6g7h8",
  "status": "complete",          // or "review_pending"
  "total": 50,
  "page": 1,
  "limit": 25,
  "results": [
    {
      "atom_id": "REQ-AP-041",
      "requirement_text": "System must support three-way matching for AP invoices",
      "classification": "FIT",
      "confidence": 0.94,
      "d365_capability": "Invoice Matching Policies",
      "d365_navigation": "AP > Invoices > Invoice matching",
      "rationale": "D365 F&O provides three-way matching as standard...",
      "module": "AccountsPayable",
      "country": "DE",
      "wave": 3,
      "reviewer_override": false,
      "evidence": {
        "top_capability_score": 0.94,
        "retrieval_confidence": "HIGH",
        "prior_fitments": [
          {"wave": 1, "country": "FR", "classification": "FIT"}
        ]
      }
    }
    // ... more results
  ],
  "summary": {
    "fit": 37,
    "partial_fit": 7,
    "gap": 6,
    "by_module": {
      "AccountsPayable": {"fit": 12, "partial_fit": 3, "gap": 2},
      "GeneralLedger": {"fit": 8, "partial_fit": 1, "gap": 1}
    }
  }
}
```

### 5. Human Review

```
GET /api/v1/d365_fo/dynafit/{batch_id}/review
Response 200:
{
  "batch_id": "bat_e5f6g7h8",
  "status": "review_pending",
  "items": [
    {
      "atom_id": "REQ-AP-055",
      "requirement_text": "Custom vendor scorecard with weighted multi-factor rating",
      "ai_classification": "GAP",
      "ai_confidence": 0.58,
      "ai_rationale": "No standard composite scoring in D365...",
      "review_reason": "low_confidence",
      "evidence": {
        "capabilities": [...],
        "prior_fitments": [],
        "anomaly_flags": []
      }
    }
  ]
}
```

**Submit review decision:**

```
POST /api/v1/d365_fo/dynafit/{batch_id}/review/{atom_id}
Content-Type: application/json

Body:
{
  "decision": "APPROVE",        // APPROVE | OVERRIDE | FLAG
  "override_classification": null,  // if OVERRIDE: "FIT" | "PARTIAL_FIT" | "GAP"
  "reason": "",                     // required if OVERRIDE
  "reviewer": "s.weber@abc.com"
}

Response 200:
{
  "atom_id": "REQ-AP-055",
  "final_classification": "GAP",
  "reviewer_override": false,
  "remaining_reviews": 4
}
```

**When all reviews complete:**
1. Backend resumes LangGraph from checkpoint (Phase 5 continues after `interrupt()`)
2. Report generator runs
3. WebSocket sends `complete` message with report URL

### 6. Download Report

```
GET /api/v1/d365_fo/dynafit/{batch_id}/report
Accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet

Response 200: Binary Excel file (fitment_matrix.xlsx)
```

### 7. Batch History

```
GET /api/v1/d365_fo/dynafit/batches
Query params:
  ?country=DE
  ?wave=3
  ?status=complete
  ?page=1&limit=10

Response 200:
{
  "batches": [
    {
      "batch_id": "bat_e5f6g7h8",
      "upload_filename": "DE_AP_Requirements_Wave3.xlsx",
      "country": "DE",
      "wave": 3,
      "status": "complete",
      "summary": {"fit": 37, "partial_fit": 7, "gap": 6},
      "created_at": "2026-03-19T14:20:00Z",
      "completed_at": "2026-03-19T14:22:00Z"
    }
  ]
}
```

---

## CELERY WORKER (BACKGROUND PROCESSING)

```python
# api/workers/tasks.py

from celery import Celery
from modules.dynafit.graph import build_dynafit_graph
import redis
import json

app = Celery("dynafit", broker="redis://localhost:6379/0")

@app.task(bind=True, max_retries=2, default_retry_delay=30)
def run_dynafit_pipeline(self, batch_id: str, upload_id: str, config: dict):
    """Execute the full DYNAFIT LangGraph pipeline."""
    
    r = redis.Redis()
    channel = f"progress:{batch_id}"
    
    def emit(msg: dict):
        """Publish progress to Redis → WebSocket."""
        r.publish(channel, json.dumps(msg))
    
    # Build graph with progress callback
    graph = build_dynafit_graph()
    
    # Load upload
    upload = load_upload(upload_id)
    
    # Initial state
    state = {
        "raw_upload": upload,
        "batch_id": batch_id,
        "config": config,
        "progress_callback": emit,   # each node calls this
    }
    
    try:
        # Run graph — checkpoints to PostgreSQL automatically
        # When graph hits interrupt() at Phase 5, it pauses
        # and returns partial state with status="interrupted"
        result = graph.invoke(state, config={
            "configurable": {
                "thread_id": batch_id,
                "product": load_product_config("d365_fo"),
            }
        })
        
        if result.get("status") == "interrupted":
            emit({"type": "review_required", "batch_id": batch_id, ...})
        else:
            emit({"type": "complete", "batch_id": batch_id, ...})
            
    except Exception as e:
        emit({"type": "error", "message": str(e), "recoverable": True})
        self.retry(exc=e)
```

**Resuming after human review:**

```python
# api/routes/dynafit.py

@router.post("/{batch_id}/review/complete")
async def complete_review(batch_id: str):
    """All reviews submitted — resume the pipeline."""
    
    graph = build_dynafit_graph()
    
    # Resume from checkpoint — LangGraph loads saved state
    result = graph.invoke(
        None,  # no new input — resume from checkpoint
        config={"configurable": {"thread_id": batch_id}},
    )
    
    return {"status": "resumed", "batch_id": batch_id}
```

---

## WEBSOCKET HANDLER

```python
# api/websocket/progress.py

from fastapi import WebSocket
import redis.asyncio as aioredis

async def progress_handler(websocket: WebSocket, batch_id: str):
    await websocket.accept()
    
    r = aioredis.Redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"progress:{batch_id}")
    
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"].decode())
    except Exception:
        pass
    finally:
        await pubsub.unsubscribe(f"progress:{batch_id}")
        await r.close()
```

---

## FRONTEND (React + Vite + TanStack Query + Zustand)

### Tech stack

```
ui/
├── src/
│   ├── api/                           # Network layer — pure async functions, no React
│   │   ├── client.ts                  # Axios instance: baseURL, auth interceptor, error interceptor
│   │   ├── dynafit.ts                 # Typed API functions for all 7 endpoints
│   │   ├── websocket.ts               # Raw WebSocket class: connect, reconnect, typed message dispatch
│   │   └── types.ts                   # TypeScript types mirroring all API request/response schemas
│   │
│   ├── stores/                        # Zustand — non-server state only (WS-driven and UI state)
│   │   ├── progressStore.ts           # WS message → typed state machine for Progress page
│   │   └── uiStore.ts                 # Active batch ID, sidebar open/close, notification queue
│   │
│   ├── hooks/                         # Stateful React glue between api/ + stores/ and pages
│   │   ├── useProgress.ts             # Opens WS, dispatches messages to progressStore
│   │   ├── useResults.ts              # TanStack Query: paginated + filtered results
│   │   ├── useReview.ts               # Review queue fetch + per-item decision mutation
│   │   ├── useBatches.ts              # Dashboard: batch history with polling
│   │   └── useUpload.ts               # Upload mutation → run mutation → returns batch_id
│   │
│   ├── components/
│   │   ├── ui/                        # Design system primitives — zero business logic
│   │   │   ├── Badge.tsx              # variant: fit | partial_fit | gap | status
│   │   │   ├── Button.tsx             # variant: primary | ghost | destructive; loading state
│   │   │   ├── Card.tsx               # surface container with optional header slot
│   │   │   ├── Skeleton.tsx           # layout-aware loading placeholders
│   │   │   ├── Progress.tsx           # linear progress bar primitive (0–100)
│   │   │   └── Toast.tsx              # error / success notifications (Radix Toast)
│   │   │
│   │   ├── layout/
│   │   │   ├── AppShell.tsx           # sidebar nav + topbar + main content area
│   │   │   └── PageHeader.tsx         # breadcrumb + page title + action slot
│   │   │
│   │   ├── upload/
│   │   │   ├── DropZone.tsx           # drag-and-drop + click; accepts .xlsx .docx .pdf only
│   │   │   └── UploadConfigForm.tsx   # product / country / wave selects + Advanced overrides panel
│   │   │
│   │   ├── progress/
│   │   │   ├── PhaseTimeline.tsx      # 5-step horizontal stepper: pending | active | complete | error
│   │   │   ├── PhaseStatsCard.tsx     # per-phase completion summary (atoms, latency, flags)
│   │   │   ├── LiveClassTable.tsx     # rows stream in during Phase 4; virtualized from first render
│   │   │   └── ReviewBanner.tsx       # HITL prompt: "N items need review" + CTA button
│   │   │
│   │   ├── results/
│   │   │   ├── SummaryCards.tsx       # total / FIT / PARTIAL_FIT / GAP count cards
│   │   │   ├── DistributionChart.tsx  # Recharts donut: classification % breakdown
│   │   │   ├── ResultsFilters.tsx     # classification + module dropdowns + confidence range slider
│   │   │   ├── ResultsTable.tsx       # @tanstack/react-virtual virtualized, sortable, filterable
│   │   │   ├── ResultRow.tsx          # expandable row: summary → rationale + evidence panel
│   │   │   └── EvidencePanel.tsx      # top-3 D365 capabilities + scores + prior fitments
│   │   │
│   │   ├── review/
│   │   │   ├── ReviewCard.tsx         # single HITL item: requirement + AI result + evidence + actions
│   │   │   ├── OverrideForm.tsx       # classification select + required reason text field
│   │   │   └── ReviewProgress.tsx     # "2 of 5 reviewed" progress indicator
│   │   │
│   │   └── dashboard/
│   │       ├── BatchTable.tsx         # history table: status badge + summary counts + links
│   │       ├── AggregateMetrics.tsx   # override rate %, avg confidence, top-5 GAP modules
│   │       └── WaveComparisonChart.tsx # Recharts bar chart: GAP count per wave
│   │
│   ├── pages/
│   │   ├── UploadPage.tsx
│   │   ├── ProgressPage.tsx
│   │   ├── ResultsPage.tsx
│   │   ├── ReviewPage.tsx
│   │   └── DashboardPage.tsx
│   │
│   ├── lib/
│   │   ├── queryClient.ts             # TanStack QueryClient: staleTime, retry, error handler
│   │   └── utils.ts                   # cn() tailwind class merger (clsx + tailwind-merge)
│   │
│   ├── App.tsx                        # React Router v6 routes with React.lazy per page
│   └── main.tsx                       # QueryClientProvider + RouterProvider mount
│
├── tests/
│   ├── unit/                          # Vitest + RTL: hooks and components in isolation
│   ├── integration/                   # Vitest + MSW: full page renders against mock handlers
│   └── e2e/                           # Playwright: full user journey against Docker backend
│
├── .env.example                       # VITE_API_URL=http://localhost:8000/api/v1
├── package.json
├── vite.config.ts
├── tailwind.config.ts
└── tsconfig.json
```

### Dependencies

```json
{
  "dependencies": {
    "react": "^18.3",
    "react-dom": "^18.3",
    "react-router-dom": "^6.22",
    "@tanstack/react-query": "^5.24",
    "@tanstack/react-virtual": "^3.2",
    "zustand": "^4.5",
    "axios": "^1.6",
    "recharts": "^2.12",
    "lucide-react": "^0.344",
    "clsx": "^2.1",
    "tailwind-merge": "^2.2",
    "@radix-ui/react-dialog": "^1.0",
    "@radix-ui/react-dropdown-menu": "^2.0",
    "@radix-ui/react-select": "^2.0",
    "@radix-ui/react-toast": "^1.1",
    "@radix-ui/react-slider": "^1.1"
  },
  "devDependencies": {
    "vite": "^5.1",
    "@vitejs/plugin-react": "^4.2",
    "tailwindcss": "^3.4",
    "typescript": "^5.3",
    "vitest": "^1.4",
    "@testing-library/react": "^14.2",
    "@testing-library/user-event": "^14.5",
    "@testing-library/jest-dom": "^6.4",
    "msw": "^2.2",
    "@playwright/test": "^1.42",
    "jsdom": "^24.0"
  }
}
```

**Why Zustand alongside TanStack Query:**
TanStack Query owns all server state (request → response). WebSocket events are push-based mutations — they have no request lifecycle. Zustand holds the WS-driven `progressStore` and ephemeral UI state (`uiStore`). The two never overlap: if data comes from an HTTP call, it lives in TanStack Query; if it arrives unsolicited over a socket, it lives in Zustand.

**Why `@tanstack/react-virtual`:**
`ResultsTable` and `LiveClassTable` are virtualized from the start. 50 requirements today is a proof-of-concept batch. Production waves can reach 500+. Adding virtualization after the fact requires a full table rewrite.

**Why `clsx` + `tailwind-merge`:**
`cn(base, conditional, override)` is the standard pattern for composing Tailwind classes safely. Without `tailwind-merge`, conflicting utility classes (e.g. `p-2 p-4`) both appear in the DOM and the last one in Tailwind's source order wins — not the one passed last to `cn()`.

---

## UI SCREENS — WHAT THE USER SEES

### Screen 1: Upload Page

**Route:** `/upload`

**User flow:**
1. Drag-and-drop file (or click to browse)
2. Select product (D365 F&O — default), country (dropdown), wave (number)
3. Optional: expand "Advanced" to override thresholds
4. Click "Start analysis"
5. Redirect to Progress page

**API calls:**
1. `POST /api/v1/upload` (on file drop) → get `upload_id`
2. `POST /api/v1/d365_fo/dynafit/run` (on button click) → get `batch_id` + `websocket_url`
3. `router.push('/progress/{batch_id}')`

### Screen 2: Progress Page

**Route:** `/progress/:batchId`

**What the user sees:**
- 5-phase horizontal progress bar (Phase 1 ██████░░ Phase 2 ░░░░░░ ... Phase 5 ░░░░░░)
- Current phase name + step name in large text
- Items processed counter: "38 / 50 requirements"
- Phase completion cards appearing as each phase finishes:
  - Phase 1: "53 atoms extracted, 50 validated, 2 flagged"
  - Phase 2: "50 contexts retrieved, avg latency 120ms"
  - Phase 3: "30 fast-track, 15 deep-reason, 5 gap-confirm"
- Classification results streaming in during Phase 4 (live table filling up)
- When Phase 5 hits HITL: banner "5 items need your review" + button → Review page

**Data source:** WebSocket `useProgress(batchId)` hook

**State machine:**
```
QUEUED → RUNNING → PHASE_1 → PHASE_2 → PHASE_3 → PHASE_4 → PHASE_5_REVIEW → COMPLETE
                                                                    ↓
                                                              REVIEW_PENDING
                                                                    ↓
                                                                COMPLETE
```

### Screen 3: Results Page

**Route:** `/results/:batchId`

**What the user sees:**
- Summary cards at top: total, FIT count (green), PARTIAL count (amber), GAP count (red)
- Donut chart: classification distribution
- Filterable table:
  - Columns: Req ID, Requirement, Module, Classification, Confidence, D365 Capability, Reviewer
  - Filters: classification dropdown, module dropdown, confidence range slider
  - Sort: click column headers
  - Pagination: 25 per page
- Click any row → expand to show: full rationale, evidence (top capabilities + scores), prior fitments, LLM trace link
- "Download Excel" button → `GET /report`

**API calls:**
- `GET /api/v1/d365_fo/dynafit/{batchId}/results?page=1&limit=25` via TanStack Query
- Filters and sorts as query params → refetch on change

### Screen 4: Review Page

**Route:** `/review/:batchId`

**What the user sees:**
- Review queue: list of items needing decision
- For each item, a card showing:
  - Requirement text (large)
  - AI classification + confidence (badge)
  - AI rationale (quoted)
  - Review reason: "Low confidence (0.58)" or "Conflict with REQ-AP-041" or "Anomaly: high cosine but low entity overlap"
  - Evidence panel:
    - Top 3 D365 capabilities with scores
    - Prior fitments from other waves (if any)
    - Anomaly flags with explanation
  - Three action buttons:
    - **Approve** (green) — accept AI classification as-is
    - **Override** (amber) — dropdown to select new classification + text field for reason
    - **Flag** (gray) — needs more info, mark for business analyst follow-up
- Progress indicator: "2 of 5 reviewed"
- When all reviewed: "Submit reviews" button → pipeline resumes → redirect to Results page

**API calls:**
- `GET /api/v1/d365_fo/dynafit/{batchId}/review` on page load
- `POST /api/v1/d365_fo/dynafit/{batchId}/review/{atomId}` per decision
- `POST /api/v1/d365_fo/dynafit/{batchId}/review/complete` after last review

### Screen 5: Dashboard

**Route:** `/dashboard`

**What the user sees:**
- Batch history table: all past runs with status, summary, dates
- Click any batch → go to Results page
- Aggregate metrics (across all batches):
  - Total requirements processed
  - Average confidence by classification
  - Human override rate (%)
  - Top 5 modules by GAP count
  - Wave-over-wave comparison chart (are GAPs decreasing?)
- Grafana embed: latency and cost metrics (iframe or link)

**API calls:**
- `GET /api/v1/d365_fo/dynafit/batches`

---

## FRONTEND STATE MANAGEMENT

### State ownership rules

| State type | Owner | Reason |
|---|---|---|
| Server data (results, review queue, batches) | TanStack Query | Request/response lifecycle, caching, pagination |
| WebSocket-driven progress | Zustand `progressStore` | Push events — no request lifecycle |
| UI ephemeral state (active batch, sidebar) | Zustand `uiStore` | Not server data, not derivable from URL |
| Form state (upload config, override reason) | React `useState` / `useForm` | Component-local, not shared |

### TanStack Query (server state)

```typescript
// lib/queryClient.ts
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});
```

```typescript
// hooks/useResults.ts
import { useQuery } from '@tanstack/react-query';
import { getResults } from '../api/dynafit';
import type { ResultsFilters } from '../api/types';

export function useResults(batchId: string, filters: ResultsFilters) {
  return useQuery({
    queryKey: ['results', batchId, filters],
    queryFn: () => getResults(batchId, filters),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    enabled: !!batchId,
  });
}
```

```typescript
// hooks/useBatches.ts
import { useQuery } from '@tanstack/react-query';
import { getBatches } from '../api/dynafit';
import type { BatchFilters } from '../api/types';

export function useBatches(filters: BatchFilters) {
  return useQuery({
    queryKey: ['batches', filters],
    queryFn: () => getBatches(filters),
    refetchInterval: 10_000,   // poll — dashboard reflects in-progress batches
  });
}
```

### Zustand progress store (WebSocket-driven state)

```typescript
// stores/progressStore.ts
import { create } from 'zustand';
import type {
  PhaseStartMsg, StepProgressMsg, PhaseCompleteMsg,
  ClassificationMsg, ReviewRequiredMsg, CompleteMsg, ErrorMsg,
} from '../api/types';

type ProgressStatus = 'idle' | 'connecting' | 'running' | 'review_pending' | 'complete' | 'error';

interface ProgressState {
  status: ProgressStatus;
  phase: number;
  phaseName: string;
  progressPct: number;
  itemsProcessed: number;
  itemsTotal: number;
  phaseStats: Partial<Record<number, PhaseCompleteMsg>>;
  classifications: ClassificationMsg[];
  reviewCount: number;
  summary: CompleteMsg['summary'] | null;
  error: string | null;
  // actions
  applyMessage: (msg: unknown) => void;
  reset: () => void;
}

const initial: Omit<ProgressState, 'applyMessage' | 'reset'> = {
  status: 'idle',
  phase: 0,
  phaseName: '',
  progressPct: 0,
  itemsProcessed: 0,
  itemsTotal: 0,
  phaseStats: {},
  classifications: [],
  reviewCount: 0,
  summary: null,
  error: null,
};

export const useProgressStore = create<ProgressState>((set) => ({
  ...initial,

  applyMessage(raw) {
    const msg = raw as { type: string } & Record<string, unknown>;
    switch (msg.type) {
      case 'phase_start':
        set((s) => ({
          ...s,
          status: 'running',
          phase: (msg as PhaseStartMsg).phase,
          phaseName: (msg as PhaseStartMsg).phase_name,
          progressPct: 0,
        }));
        break;
      case 'step_progress': {
        const m = msg as StepProgressMsg;
        set((s) => ({
          ...s,
          progressPct: m.progress_pct,
          itemsProcessed: m.items_processed,
          itemsTotal: m.items_total,
        }));
        break;
      }
      case 'phase_complete': {
        const m = msg as PhaseCompleteMsg;
        set((s) => ({
          ...s,
          phaseStats: { ...s.phaseStats, [m.phase]: m },
        }));
        break;
      }
      case 'classification':
        set((s) => ({
          ...s,
          classifications: [...s.classifications, msg as ClassificationMsg],
        }));
        break;
      case 'review_required':
        set((s) => ({
          ...s,
          status: 'review_pending',
          reviewCount: (msg as ReviewRequiredMsg).review_items,
        }));
        break;
      case 'complete':
        set((s) => ({
          ...s,
          status: 'complete',
          summary: (msg as CompleteMsg).summary,
        }));
        break;
      case 'error':
        set((s) => ({
          ...s,
          error: (msg as ErrorMsg).message,
          status: (msg as ErrorMsg).recoverable ? s.status : 'error',
        }));
        break;
    }
  },

  reset() {
    set(initial);
  },
}));
```

### WebSocket hook (connects WS to Zustand store)

**Bug in original spec:** `ws.onclose = () => { setTimeout(() => useProgress(batchId), 3000); }` calls a React hook inside a non-hook callback, violating the Rules of Hooks. The reconnect below uses `useRef` + exponential backoff and reconciles missed events via REST on reconnect.

```typescript
// hooks/useProgress.ts
import { useEffect, useRef } from 'react';
import { useProgressStore } from '../stores/progressStore';
import { getResults } from '../api/dynafit';
import { queryClient } from '../lib/queryClient';

const WS_BASE = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000';

export function useProgress(batchId: string) {
  const applyMessage = useProgressStore((s) => s.applyMessage);
  const reset = useProgressStore((s) => s.reset);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const unmountedRef = useRef(false);

  useEffect(() => {
    unmountedRef.current = false;
    reset();

    function connect() {
      if (unmountedRef.current) return;

      const ws = new WebSocket(`${WS_BASE}/api/v1/ws/progress/${batchId}`);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        applyMessage(JSON.parse(event.data as string));
      };

      ws.onopen = () => {
        retryRef.current = 0;
        // Reconcile any events missed during disconnect
        queryClient.invalidateQueries({ queryKey: ['results', batchId] });
      };

      ws.onclose = () => {
        if (unmountedRef.current) return;
        // Exponential backoff: 1s → 2s → 4s → 8s → 16s → cap at 30s
        const delay = Math.min(1_000 * 2 ** retryRef.current, 30_000);
        retryRef.current += 1;
        setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      unmountedRef.current = true;
      wsRef.current?.close();
    };
  }, [batchId, applyMessage, reset]);

  // Components read directly from the store — no return value needed here
}
```

---

## API CLIENT

```typescript
// api/client.ts
import axios, { type AxiosError } from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

// Attach JWT on every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Centralised error handling — don't duplicate in every API function
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  },
);

export default api;
```

```typescript
// api/types.ts  — TypeScript mirror of all API schemas

export type Classification = 'FIT' | 'PARTIAL_FIT' | 'GAP';
export type BatchStatus = 'queued' | 'running' | 'review_pending' | 'complete' | 'failed';
export type ReviewDecisionType = 'APPROVE' | 'OVERRIDE' | 'FLAG';

export interface UploadResponse {
  upload_id: string;
  filename: string;
  size_bytes: number;
  detected_format: string;
  status: 'uploaded';
}

export interface RunResponse {
  batch_id: string;
  upload_id: string;
  status: 'queued';
  websocket_url: string;
}

export interface ResultItem {
  atom_id: string;
  requirement_text: string;
  classification: Classification;
  confidence: number;
  d365_capability: string;
  d365_navigation: string;
  rationale: string;
  module: string;
  country: string;
  wave: number;
  reviewer_override: boolean;
  evidence: {
    top_capability_score: number;
    retrieval_confidence: 'HIGH' | 'MEDIUM' | 'LOW';
    prior_fitments: { wave: number; country: string; classification: Classification }[];
  };
}

export interface ResultsResponse {
  batch_id: string;
  status: BatchStatus;
  total: number;
  page: number;
  limit: number;
  results: ResultItem[];
  summary: {
    fit: number;
    partial_fit: number;
    gap: number;
    by_module: Record<string, { fit: number; partial_fit: number; gap: number }>;
  };
}

export interface ResultsFilters {
  classification?: Classification;
  module?: string;
  sort?: string;
  order?: 'asc' | 'desc';
  page: number;
  limit: number;
}

export interface ReviewItem {
  atom_id: string;
  requirement_text: string;
  ai_classification: Classification;
  ai_confidence: number;
  ai_rationale: string;
  review_reason: 'low_confidence' | 'conflict' | 'anomaly';
  evidence: {
    capabilities: { name: string; score: number }[];
    prior_fitments: ResultItem['evidence']['prior_fitments'];
    anomaly_flags: { flag: string; explanation: string }[];
  };
}

export interface ReviewResponse {
  batch_id: string;
  status: 'review_pending';
  items: ReviewItem[];
}

export interface ReviewDecision {
  decision: ReviewDecisionType;
  override_classification: Classification | null;
  reason: string;
  reviewer: string;
}

export interface ReviewDecisionResponse {
  atom_id: string;
  final_classification: Classification;
  reviewer_override: boolean;
  remaining_reviews: number;
}

export interface BatchSummary {
  batch_id: string;
  upload_filename: string;
  country: string;
  wave: number;
  status: BatchStatus;
  summary: { fit: number; partial_fit: number; gap: number };
  created_at: string;
  completed_at: string | null;
}

export interface BatchListResponse {
  batches: BatchSummary[];
}

export interface BatchFilters {
  country?: string;
  wave?: number;
  status?: BatchStatus;
  page?: number;
  limit?: number;
}

// WebSocket message types
export interface PhaseStartMsg {
  type: 'phase_start';
  phase: number;
  phase_name: string;
  total_phases: number;
  timestamp: string;
}
export interface StepProgressMsg {
  type: 'step_progress';
  phase: number;
  step: string;
  sub_step: string;
  progress_pct: number;
  items_processed: number;
  items_total: number;
  timestamp: string;
}
export interface PhaseCompleteMsg {
  type: 'phase_complete';
  phase: number;
  phase_name: string;
  atoms_produced?: number;
  atoms_validated?: number;
  atoms_flagged?: number;
  atoms_rejected?: number;
  latency_ms: number;
  timestamp: string;
}
export interface ClassificationMsg {
  type: 'classification';
  atom_id: string;
  requirement_text: string;
  classification: Classification;
  confidence: number;
  module: string;
  rationale: string;
}
export interface ReviewRequiredMsg {
  type: 'review_required';
  batch_id: string;
  review_items: number;
  reasons: Record<string, number>;
  review_url: string;
}
export interface CompleteMsg {
  type: 'complete';
  batch_id: string;
  summary: { total: number; fit: number; partial_fit: number; gap: number };
  report_url: string;
  latency_total_ms: number;
}
export interface ErrorMsg {
  type: 'error';
  phase: number;
  message: string;
  recoverable: boolean;
  retry_at?: string;
}
```

```typescript
// api/dynafit.ts
import api from './client';
import type {
  UploadResponse, RunResponse, ResultsResponse, ResultsFilters,
  ReviewResponse, ReviewDecision, ReviewDecisionResponse,
  BatchListResponse, BatchFilters,
} from './types';

export async function uploadFile(
  file: File,
  meta: { product: string; country: string; wave: number },
): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('product', meta.product);
  form.append('country', meta.country);
  form.append('wave', String(meta.wave));
  const { data } = await api.post<UploadResponse>('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function startAnalysis(
  uploadId: string,
  configOverrides?: Record<string, unknown>,
): Promise<RunResponse> {
  const { data } = await api.post<RunResponse>('/d365_fo/dynafit/run', {
    upload_id: uploadId,
    config_overrides: configOverrides,
  });
  return data;
}

export async function getResults(
  batchId: string,
  filters: ResultsFilters,
): Promise<ResultsResponse> {
  const params = new URLSearchParams();
  if (filters.classification) params.set('classification', filters.classification);
  if (filters.module) params.set('module', filters.module);
  if (filters.sort) params.set('sort', filters.sort);
  if (filters.order) params.set('order', filters.order);
  params.set('page', String(filters.page));
  params.set('limit', String(filters.limit));
  const { data } = await api.get<ResultsResponse>(
    `/d365_fo/dynafit/${batchId}/results?${params}`,
  );
  return data;
}

export async function getReview(batchId: string): Promise<ReviewResponse> {
  const { data } = await api.get<ReviewResponse>(
    `/d365_fo/dynafit/${batchId}/review`,
  );
  return data;
}

export async function submitReview(
  batchId: string,
  atomId: string,
  decision: ReviewDecision,
): Promise<ReviewDecisionResponse> {
  const { data } = await api.post<ReviewDecisionResponse>(
    `/d365_fo/dynafit/${batchId}/review/${atomId}`,
    decision,
  );
  return data;
}

export async function completeReview(batchId: string): Promise<void> {
  await api.post(`/d365_fo/dynafit/${batchId}/review/complete`);
}

export async function getBatches(filters: BatchFilters): Promise<BatchListResponse> {
  const params = new URLSearchParams();
  if (filters.country) params.set('country', filters.country);
  if (filters.wave) params.set('wave', String(filters.wave));
  if (filters.status) params.set('status', filters.status);
  if (filters.page) params.set('page', String(filters.page));
  if (filters.limit) params.set('limit', String(filters.limit));
  const { data } = await api.get<BatchListResponse>(`/d365_fo/dynafit/batches?${params}`);
  return data;
}

// Returns a direct URL string — used as an <a href> for binary download, not fetched via Axios
export function getReportUrl(batchId: string): string {
  return `${api.defaults.baseURL}/d365_fo/dynafit/${batchId}/report`;
}
```

---

## DATABASE SCHEMA (PostgreSQL)

```sql
CREATE TABLE batches (
    id          TEXT PRIMARY KEY,           -- bat_e5f6g7h8
    upload_id   TEXT NOT NULL,
    product     TEXT NOT NULL DEFAULT 'd365_fo',
    country     TEXT NOT NULL,
    wave        INT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued|running|review_pending|complete|failed
    config      JSONB DEFAULT '{}',
    summary     JSONB,                      -- {fit: 37, partial_fit: 7, gap: 6}
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE classifications (
    id              SERIAL PRIMARY KEY,
    batch_id        TEXT REFERENCES batches(id),
    atom_id         TEXT NOT NULL,
    requirement_text TEXT NOT NULL,
    module          TEXT NOT NULL,
    classification  TEXT NOT NULL,           -- FIT|PARTIAL_FIT|GAP
    confidence      FLOAT NOT NULL,
    d365_capability TEXT,
    d365_navigation TEXT,
    rationale       TEXT NOT NULL,
    evidence        JSONB NOT NULL,          -- capabilities, prior_fitments, scores
    reviewer        TEXT,
    reviewer_override BOOLEAN DEFAULT FALSE,
    override_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE review_queue (
    id              SERIAL PRIMARY KEY,
    batch_id        TEXT REFERENCES batches(id),
    atom_id         TEXT NOT NULL,
    review_reason   TEXT NOT NULL,            -- low_confidence|conflict|anomaly
    status          TEXT DEFAULT 'pending',   -- pending|approved|overridden|flagged
    decision        JSONB,
    reviewer        TEXT,
    decided_at      TIMESTAMPTZ
);

-- Index for fast result queries
CREATE INDEX idx_classifications_batch ON classifications(batch_id);
CREATE INDEX idx_classifications_filter ON classifications(batch_id, classification, module);
CREATE INDEX idx_review_queue_batch ON review_queue(batch_id, status);
```

---

## VITE + PROXY CONFIGURATION

**Ordering rule:** The WS proxy entry must be declared before the `/api` catch-all. Vite matches proxy rules in declaration order; if `/api` is listed first, it absorbs WebSocket upgrade requests before the WS-specific rule is ever evaluated.

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),  // import from '@/api/...' instead of '../../api/...'
    },
  },
  server: {
    port: 3000,
    proxy: {
      // WS rule FIRST — must precede the /api catch-all
      '/api/v1/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      // REST catch-all SECOND
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
```

---

## FRONTEND TESTING STRATEGY

No live backend in any unit or integration test. MSW intercepts at the network level using the same request shapes defined in `api/types.ts`.

### Unit tests (Vitest + React Testing Library)

What to test:
- All custom hooks (`useProgress`, `useResults`, `useReview`, `useUpload`, `useBatches`) in isolation with MSW mock handlers
- All `ui/` primitive components: render, variant classes, interaction events
- `progressStore`: every `applyMessage` branch produces correct state transition
- `utils.ts`: `cn()` class merging correctness

What NOT to test at unit level:
- Page-level layout (covered by integration tests)
- Network timing or WebSocket reconnect delays (covered by E2E)

```typescript
// tests/unit/stores/progressStore.test.ts — example
import { describe, it, expect, beforeEach } from 'vitest';
import { useProgressStore } from '@/stores/progressStore';

describe('progressStore', () => {
  beforeEach(() => useProgressStore.getState().reset());

  it('phase_start transitions status to running', () => {
    useProgressStore.getState().applyMessage({
      type: 'phase_start', phase: 1, phase_name: 'Ingestion', total_phases: 5,
      timestamp: '2026-03-19T14:22:00Z',
    });
    const s = useProgressStore.getState();
    expect(s.status).toBe('running');
    expect(s.phase).toBe(1);
    expect(s.progressPct).toBe(0);
  });

  it('review_required transitions status to review_pending', () => {
    useProgressStore.getState().applyMessage({
      type: 'review_required', batch_id: 'bat_1', review_items: 5,
      reasons: { low_confidence: 3 }, review_url: '/review/bat_1',
    });
    expect(useProgressStore.getState().status).toBe('review_pending');
    expect(useProgressStore.getState().reviewCount).toBe(5);
  });
});
```

### Integration tests (Vitest + MSW)

What to test:
- Full page renders: data fetched, transformed, displayed correctly
- TanStack Query cache invalidation after mutations (submit review → results refetch)
- Filter/sort param changes produce correct query keys and API calls
- Error states: 500 from server → error UI shown, no crash

```typescript
// tests/integration/pages/ResultsPage.test.tsx — example
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResultsPage } from '@/pages/ResultsPage';
import { server } from '../mocks/server';   // MSW server
import { http, HttpResponse } from 'msw';
import { resultsFixture } from '../fixtures/results';

it('displays summary counts from API response', async () => {
  server.use(
    http.get('/api/v1/d365_fo/dynafit/:batchId/results', () =>
      HttpResponse.json(resultsFixture),
    ),
  );
  render(<ResultsPage />, { wrapper: Providers });
  expect(await screen.findByText('37')).toBeInTheDocument(); // FIT count
  expect(await screen.findByText('6')).toBeInTheDocument();  // GAP count
});
```

### E2E tests (Playwright)

Runs against the live Docker backend (`make dev`). Uses the same user journey defined in [THE FULL USER JOURNEY](#the-full-user-journey-end-to-end).

Test files:
```
tests/e2e/
├── upload.spec.ts         # upload file → verify format detection + redirect
├── progress.spec.ts       # WS messages → correct phase timeline rendering
├── review.spec.ts         # approve + override items → submit → pipeline resumes
├── results.spec.ts        # filter, sort, pagination, Excel download
└── reconnect.spec.ts      # close WS mid-run → reconnect → state reconciled via REST
```

MSW mock handlers live at `tests/mocks/handlers.ts` and mirror every API endpoint in this spec. Fixtures at `tests/fixtures/*.json` capture realistic response shapes for all 7 endpoints.

---

## THE FULL USER JOURNEY (END TO END)

1. User opens `/upload` → drags `DE_AP_Requirements_Wave3.xlsx`
2. File uploads → format detected as XLSX → green checkmark
3. User selects country=DE, wave=3, clicks "Start analysis"
4. Redirect to `/progress/bat_e5f6g7h8`
5. Progress bar fills: Phase 1 ████ ... 53 atoms extracted
6. Phase 2 fills: retrieving context for 50 atoms...
7. Phase 3 fills: 30 fast-track, 15 deep-reason, 5 gap-confirm
8. Phase 4: classifications stream in one by one, table populates live
9. Phase 5: banner appears — "5 items need your review"
10. User clicks "Review" → `/review/bat_e5f6g7h8`
11. Reviews each item: approves 4, overrides 1 (GAP → FIT, reason: "Custom config already built in Wave 2")
12. Clicks "Submit reviews" → pipeline resumes
13. Redirect to `/results/bat_e5f6g7h8`
14. Final table: 37 FIT, 7 PARTIAL, 6 GAP
15. Clicks "Download Excel" → fitment_matrix.xlsx
16. Clicks "Dashboard" → sees this batch alongside Wave 1 and Wave 2 history
