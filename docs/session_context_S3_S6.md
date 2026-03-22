# Session Context: Build S3–S6 UI Features

> Paste this into a new Claude Code session to build the remaining UI features fast.
> All backend APIs and types already exist. This is **UI-only work**.

---

## What's Already Built (DO NOT rebuild)

### Backend (100% complete)
- **API models** (`api/models.py`): `ResultItem`, `ReviewItem`, `BatchRecord`, `BatchSummary`, `PublicResultsResponse` — all have `configuration_steps`, `dev_effort`, `gap_type`, `config_steps`, `gap_description`
- **API routes** (`api/routes/dynafit.py`): All 9 endpoints working — upload, run, results, review, review/complete, report download, batch listing, public results, public batch listing
- **Worker** (`api/workers/tasks.py`): Serializes all fields to Redis for both complete and HITL paths
- **WebSocket** (`api/websocket/progress.py`): Emits `WSComplete` with `results_url` field

### UI Infrastructure (100% complete)
- **Router** (`ui/src/App.tsx`): 5 routes — `/dashboard`, `/upload`, `/progress/:batchId`, `/results/:batchId`, `/review/:batchId`
- **API client** (`ui/src/api/dynafit.ts`): `uploadFile`, `runAnalysis`, `getResults`, `getReview`, `submitReview`, `downloadReport`, `getBatches`
- **Types** (`ui/src/api/types.ts`): All TS interfaces match backend models. Key types: `FitmentResult`, `ReviewItem`, `ResultsSummary`, `Batch`, `WSMessage` union
- **Hooks**: `useUpload`, `useResults`, `useBatches`, `useProgress`, `useReview`
- **Stores**: `progressStore` (Zustand — dispatches WSMessage), `uiStore` (sidebar, notifications)
- **Design system**: `Badge`, `Button`, `Card`, `Skeleton`, `Progress`, `Toast`
- **WebSocket**: `DynafitWebSocket` class with reconnect logic

### UI Pages (all exist but some need upgrades)
- **UploadPage** — complete, no changes needed
- **ProgressPage** — complete with phase timeline, stats cards, live classification stream, review banner, completion summary
- **ReviewPage** — complete with tabs (FIT/PARTIAL_FIT/GAP), bulk actions, review cards with evidence accordion, override form, auto-approved table
- **ResultsPage** — exists with summary cards, distribution chart, filters, virtualized table with pagination
- **DashboardPage** — exists with aggregate metrics, wave comparison chart, batch history table

---

## What Needs Building (S3–S6)

### S3: Completion Panel Enhancement (ProgressPage)
**Current state**: ProgressPage already shows a basic completion panel (`complete && (...)` block at line 90-123 of `ProgressPage.tsx`) with 4 stat cards and a "View detailed results" button.

**What to add**:
- Add "Download Report" button next to "View detailed results" (use `downloadReport()` from `api/dynafit.ts`)
- Add "Share Results" copy-link button (URL: `/results/{batchId}`)
- `WSComplete` already has `report_url` and `results_url` fields — wire them up
- The `CompleteSummary` in `progressStore.ts` already stores `reportUrl` — just needs UI buttons

**Files to modify**: `ui/src/pages/ProgressPage.tsx`, possibly `ui/src/stores/progressStore.ts` (to store `results_url`)

### S4: Results Page Upgrade
**Current state**: ResultsPage has SummaryCards, DistributionChart, ResultsFilters, ResultsTable. The table uses `@tanstack/react-virtual` for virtualization.

**What to add**:
- **Module grouping**: Results are already returned with `module` field — add a module filter dropdown or group-by-module view
- **Evidence panel**: `EvidencePanel.tsx` component exists but may need wiring — `ResultRow.tsx` should expand to show it
- **Classification-specific details**: `FitmentResult` has `configuration_steps` (PARTIAL_FIT), `dev_effort`/`gap_type`/`gap_description` (GAP) — show these in the expanded row or evidence panel
- **Export button**: "Download Excel" button exists on header (line 61-69) and calls `downloadReport()` — verify it works

**Files to touch**: `ui/src/components/results/ResultRow.tsx`, `ui/src/components/results/EvidencePanel.tsx`, `ui/src/components/results/ResultsFilters.tsx`, `ui/src/pages/ResultsPage.tsx`

### S5: Export XLSX
**Current state**: The download button in ResultsPage calls `downloadReport(batchId)` which hits `GET /d365_fo/dynafit/{batch_id}/report`. Backend returns a zip file.

**What might need**:
- Verify the report route returns actual data (it reads `report_path` from batch state)
- If report generation isn't implemented in Phase 5 yet, this button will 404 — could add graceful handling
- Consider adding a client-side CSV export as fallback using the results data already in memory

**Files to touch**: `ui/src/pages/ResultsPage.tsx` (add CSV fallback), `ui/src/api/dynafit.ts` (already has `downloadReport`)

### S6: Dashboard Enhancement
**Current state**: DashboardPage shows AggregateMetrics, WaveComparisonChart, BatchTable.

**What to add**:
- **Status filter**: BatchTable should filter by status (queued/running/review_pending/complete/failed)
- **Search/sort**: Allow sorting batch table by date, status, country
- **Batch actions**: Click row → navigate to results (already works in BatchTable)
- **Refresh**: `useBatches` already has `refetchInterval: 30_000` — batches auto-refresh

**Files to touch**: `ui/src/pages/DashboardPage.tsx`, `ui/src/components/dashboard/BatchTable.tsx`, `ui/src/components/dashboard/AggregateMetrics.tsx`

---

## Patterns to Follow

### Component convention
```tsx
// All components use this pattern:
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import type { Classification } from '@/api/types'

// Classification colors (already in tailwind config):
// fit-text, fit-muted, partial-text, partial-muted, gap-text, gap-muted
// accent, accent-glow, bg-base, bg-surface, bg-raised, bg-border
// text-primary, text-secondary, text-muted

// Badge accepts variant as Classification | BatchStatus
<Badge variant="FIT" />
<Badge variant="complete" />
```

### Hook convention
```tsx
// All data hooks use @tanstack/react-query
import { useQuery } from '@tanstack/react-query'
import { getResults } from '@/api/dynafit'
export function useResults(batchId: string, query = {}) {
  return useQuery({
    queryKey: ['results', batchId, query],
    queryFn: () => getResults(batchId, query),
    enabled: !!batchId,
  })
}
```

### API client convention
```tsx
// All API calls go through apiClient (axios instance)
import { apiClient } from './client'
// Base URL: VITE_API_URL ?? '/api/v1'
// Routes prefixed with /d365_fo/dynafit/
```

### Layout convention
```tsx
// All pages follow this structure:
<div>
  <PageHeader title="..." description="..." action={<Button />} />
  <div className="space-y-4 px-6 pb-6">
    {/* content */}
  </div>
</div>
```

---

## File Map (what exists where)

```
ui/src/
├── api/
│   ├── client.ts          # axios instance
│   ├── dynafit.ts         # 7 API functions
│   ├── types.ts           # all TS interfaces (287 lines)
│   └── websocket.ts       # DynafitWebSocket class
├── components/
│   ├── dashboard/
│   │   ├── AggregateMetrics.tsx
│   │   ├── BatchTable.tsx
│   │   └── WaveComparisonChart.tsx
│   ├── layout/
│   │   ├── AppShell.tsx   # sidebar + topbar + Outlet
│   │   └── PageHeader.tsx
│   ├── progress/
│   │   ├── LiveClassTable.tsx
│   │   ├── PhaseStatsCard.tsx
│   │   ├── PhaseTimeline.tsx
│   │   └── ReviewBanner.tsx
│   ├── results/
│   │   ├── DistributionChart.tsx
│   │   ├── EvidencePanel.tsx
│   │   ├── ResultRow.tsx
│   │   ├── ResultsFilters.tsx
│   │   ├── ResultsTable.tsx
│   │   └── SummaryCards.tsx
│   ├── review/
│   │   ├── BulkActions.tsx
│   │   ├── OverrideForm.tsx
│   │   ├── ReviewCard.tsx
│   │   ├── ReviewProgress.tsx
│   │   └── ReviewTabs.tsx
│   ├── ui/
│   │   ├── Badge.tsx, Button.tsx, Card.tsx
│   │   ├── Progress.tsx, Skeleton.tsx, Toast.tsx
│   └── upload/
│       ├── DropZone.tsx
│       └── UploadConfigForm.tsx
├── hooks/
│   ├── useBatches.ts, useProgress.ts, useResults.ts
│   ├── useReview.ts, useUpload.ts
├── lib/
│   └── utils.ts           # cn, formatConfidence, formatDate, formatBytes, etc.
├── pages/
│   ├── DashboardPage.tsx, ProgressPage.tsx, ResultsPage.tsx
│   ├── ReviewPage.tsx, UploadPage.tsx
├── stores/
│   ├── progressStore.ts   # Zustand store for WS messages
│   └── uiStore.ts         # sidebar state, notifications
├── App.tsx                # router config
└── main.tsx
```

---

## Key Data Shapes (for quick reference)

```typescript
// FitmentResult (results table row)
{
  atom_id, requirement_text, classification, confidence,
  module, country, wave, rationale, reviewer_override,
  d365_capability, d365_navigation, evidence,
  config_steps, gap_description,           // free text from LLM
  configuration_steps,                     // string[] (PARTIAL_FIT)
  dev_effort: 'S'|'M'|'L',               // GAP only
  gap_type,                               // GAP only
}

// WSComplete (progress page terminal event)
{
  event: 'complete', batch_id, total, fit_count, partial_fit_count,
  gap_count, review_count, report_url, results_url
}

// Batch (dashboard table row)
{
  batch_id, upload_filename, product, country, wave,
  status, summary: { fit, partial_fit, gap }, created_at, completed_at
}
```

---

## How to Run

```bash
# Set API key in .env first
make dev           # starts 10-service Docker stack
make seed-kb-lite  # populates Qdrant with D365 capabilities
# Open http://localhost:5173
```

---

## Rules

- Read existing component code before modifying — don't guess the API
- Use the existing design tokens (fit-text, partial-muted, etc.) — don't invent new colors
- No new dependencies unless absolutely necessary
- Follow the existing PageHeader + space-y-4 layout pattern
- All API functions and types already exist — wire them up, don't recreate
