// ─── Shared enums ────────────────────────────────────────────────────────────

export type Classification = 'FIT' | 'PARTIAL_FIT' | 'GAP'
export type BatchStatus = 'queued' | 'running' | 'review_pending' | 'complete' | 'failed'
export type ReviewDecision = 'APPROVE' | 'OVERRIDE' | 'FLAG'

// ─── Upload ───────────────────────────────────────────────────────────────────

export interface UploadRequest {
  file: File
  product: string
  country: string
  wave: number
}

export interface UploadResponse {
  upload_id: string
  filename: string
  size_bytes: number
  detected_format: string
  status: 'uploaded'
}

// ─── Run ──────────────────────────────────────────────────────────────────────

export interface RunRequest {
  upload_id: string
  config_overrides?: {
    fit_confidence_threshold?: number
    auto_approve_with_history?: boolean
  }
}

export interface RunResponse {
  batch_id: string
  upload_id: string
  status: 'queued'
  websocket_url: string
}

// ─── Results ─────────────────────────────────────────────────────────────────

export interface FitmentEvidence {
  top_capability_score: number
  retrieval_confidence: 'HIGH' | 'MEDIUM' | 'LOW'
  prior_fitments: Array<{
    wave: number
    country: string
    classification: Classification
  }>
}

export interface FitmentResult {
  atom_id: string
  requirement_text: string
  classification: Classification
  confidence: number
  d365_capability: string
  d365_navigation: string
  rationale: string
  module: string
  country: string
  wave: number
  reviewer_override: boolean
  evidence: FitmentEvidence
}

export interface ModuleSummary {
  fit: number
  partial_fit: number
  gap: number
}

export interface ResultsSummary {
  fit: number
  partial_fit: number
  gap: number
  by_module: Record<string, ModuleSummary>
}

export interface ResultsResponse {
  batch_id: string
  status: BatchStatus
  total: number
  page: number
  limit: number
  results: FitmentResult[]
  summary: ResultsSummary
}

export interface ResultsQuery {
  classification?: Classification
  module?: string
  sort?: string
  order?: 'asc' | 'desc'
  page?: number
  limit?: number
}

// ─── Review ───────────────────────────────────────────────────────────────────

export interface Capability {
  name: string
  score: number
  navigation: string
}

export interface ReviewItemEvidence {
  capabilities: Capability[]
  prior_fitments: Array<{ wave: number; country: string; classification: Classification }>
  anomaly_flags: string[]
}

export interface ReviewItem {
  atom_id: string
  requirement_text: string
  ai_classification: Classification
  ai_confidence: number
  ai_rationale: string
  review_reason: 'low_confidence' | 'conflict' | 'anomaly'
  evidence: ReviewItemEvidence
}

export interface ReviewResponse {
  batch_id: string
  status: 'review_pending'
  items: ReviewItem[]
}

export interface ReviewSubmitRequest {
  decision: ReviewDecision
  override_classification?: Classification | null
  reason?: string
  reviewer: string
}

export interface ReviewSubmitResponse {
  atom_id: string
  final_classification: Classification
  reviewer_override: boolean
  remaining_reviews: number
}

// ─── Batches ─────────────────────────────────────────────────────────────────

export interface BatchSummary {
  fit: number
  partial_fit: number
  gap: number
}

export interface Batch {
  batch_id: string
  upload_filename: string
  country: string
  wave: number
  status: BatchStatus
  summary: BatchSummary
  created_at: string
  completed_at: string | null
}

export interface BatchesQuery {
  country?: string
  wave?: number
  status?: BatchStatus
  page?: number
  limit?: number
}

export interface BatchesResponse {
  batches: Batch[]
  total: number
  page: number
  limit: number
}

// ─── WebSocket message types ──────────────────────────────────────────────────

export interface WSPhaseStart {
  type: 'phase_start'
  phase: number
  phase_name: string
  total_phases: number
  timestamp: string
}

export interface WSStepProgress {
  type: 'step_progress'
  phase: number
  step: string
  sub_step: string
  progress_pct: number
  items_processed: number
  items_total: number
  timestamp: string
}

export interface WSPhaseComplete {
  type: 'phase_complete'
  phase: number
  phase_name: string
  atoms_produced: number
  atoms_validated: number
  atoms_flagged: number
  atoms_rejected: number
  latency_ms: number
  timestamp: string
}

export interface WSClassification {
  type: 'classification'
  atom_id: string
  requirement_text: string
  classification: Classification
  confidence: number
  module: string
  rationale: string
}

export interface WSReviewRequired {
  type: 'review_required'
  batch_id: string
  review_items: number
  reasons: {
    low_confidence: number
    conflicts: number
    anomalies: number
  }
  review_url: string
}

export interface WSComplete {
  type: 'complete'
  batch_id: string
  summary: BatchSummary & { total: number }
  report_url: string
  latency_total_ms: number
}

export interface WSError {
  type: 'error'
  phase?: number
  message: string
  recoverable: boolean
  retry_at?: string
}

export type WSMessage =
  | WSPhaseStart
  | WSStepProgress
  | WSPhaseComplete
  | WSClassification
  | WSReviewRequired
  | WSComplete
  | WSError
