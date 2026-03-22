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
  status: 'uploaded' | 'already_exists'
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
  config_steps: string | null
  gap_description: string | null
  configuration_steps: string[] | null
  dev_effort: 'S' | 'M' | 'L' | null
  gap_type: string | null
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
  module: string
  evidence: ReviewItemEvidence
  config_steps: string | null
  gap_description: string | null
  configuration_steps: string[] | null
  dev_effort: 'S' | 'M' | 'L' | null
  gap_type: string | null
}

export interface AutoApprovedItem {
  atom_id: string
  requirement_text: string
  classification: Classification
  confidence: number
  module: string
  rationale: string
  d365_capability: string
  d365_navigation: string
  config_steps: string | null
  configuration_steps: string[] | null
  gap_description: string | null
  gap_type: string | null
  dev_effort: 'S' | 'M' | 'L' | null
}

export interface ReviewResponse {
  batch_id: string
  status: 'review_pending'
  items: ReviewItem[]
  auto_approved: AutoApprovedItem[]
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
  product: string
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

// ─── Journey (requirement traceability) ──────────────────────────────────────

export interface JourneyIngest {
  atom_id: string
  requirement_text: string
  module: string
  intent: string
  priority: string
  entity_hints: string[]
  specificity_score: number
  completeness_score: number
  content_type: string
  source_refs: string[]
}

export interface JourneyCapability {
  name: string
  score: number
  navigation: string
}

export interface JourneyDocRef {
  title: string
  score: number
}

export interface PriorFitment {
  wave: number
  country: string
  classification: string
}

export interface JourneyRetrieve {
  capabilities: JourneyCapability[]
  ms_learn_refs: JourneyDocRef[]
  prior_fitments: PriorFitment[]
  retrieval_confidence: 'HIGH' | 'MEDIUM' | 'LOW'
}

export interface SignalBreakdown {
  embedding_cosine: number
  entity_overlap: number
  token_ratio: number
  historical_alignment: number
  rerank_score: number
}

export interface JourneyMatch {
  signal_breakdown: SignalBreakdown
  composite_score: number
  route: string
  anomaly_flags: string[]
}

export interface JourneyClassify {
  classification: Classification
  confidence: number
  rationale: string
  route_used: string
  llm_calls_used: number
  d365_capability: string
  d365_navigation: string
}

export interface JourneyOutput {
  classification: Classification
  confidence: number
  config_steps: string | null
  configuration_steps: string[] | null
  gap_description: string | null
  gap_type: string | null
  dev_effort: string | null
  reviewer_override: boolean
}

export interface AtomJourney {
  atom_id: string
  ingest: JourneyIngest
  retrieve: JourneyRetrieve
  match: JourneyMatch
  classify: JourneyClassify
  output: JourneyOutput
}

export interface JourneyResponse {
  batch_id: string
  atoms: AtomJourney[]
}

// ─── Pipeline progress (durable phase state) ─────────────────────────────────

export interface PhaseProgressItem {
  phase: number
  phase_name: string
  status: 'pending' | 'active' | 'complete'
  current_step: string | null
  progress_pct: number
  atoms_produced: number
  atoms_validated: number
  atoms_flagged: number
  latency_ms: number | null
}

export interface ProgressClassificationItem {
  atom_id: string
  classification: Classification
  confidence: number
}

export interface ProgressResponse {
  batch_id: string
  status: string
  phases: PhaseProgressItem[]
  classifications: ProgressClassificationItem[]
}

// ─── WebSocket message types ──────────────────────────────────────────────────

export interface WSPhaseStart {
  event: 'phase_start'
  batch_id: string
  phase: number
  phase_name: string
  timestamp: string
}

export interface WSStepProgress {
  event: 'step_progress'
  batch_id: string
  phase: number
  step: string
  completed: number
  total: number
  timestamp: string
}

export interface WSPhaseComplete {
  event: 'phase_complete'
  batch_id: string
  phase: number
  phase_name: string
  atoms_produced: number
  atoms_validated: number
  atoms_flagged: number
  latency_ms: number
  timestamp: string
}

export interface WSClassification {
  event: 'classification'
  batch_id: string
  atom_id: string
  classification: Classification
  confidence: number
  timestamp: string
}

export interface WSReviewRequired {
  event: 'review_required'
  batch_id: string
  review_items: number
  reasons: {
    low_confidence: number
    conflicts?: number
    anomalies?: number
  }
  review_url: string
}

export interface WSComplete {
  event: 'complete'
  batch_id: string
  total: number
  fit_count: number
  partial_fit_count: number
  gap_count: number
  review_count: number
  report_url: string | null
  results_url: string | null
}

export interface WSError {
  event: 'error'
  batch_id: string
  phase?: number | null
  atom_id?: string | null
  error_type: string
  message: string
}

export type WSMessage =
  | WSPhaseStart
  | WSStepProgress
  | WSPhaseComplete
  | WSClassification
  | WSReviewRequired
  | WSComplete
  | WSError

// Discriminator used by the backend (Pydantic `event` field)
export type WSEventType = WSMessage['event']
