import { http, HttpResponse } from 'msw'
import type {
  UploadResponse,
  RunResponse,
  ResultsResponse,
  ReviewResponse,
  ReviewSubmitResponse,
  BatchesResponse,
} from '@/api/types'

// MSW v2 node handlers require absolute URLs
const BASE = 'http://localhost/api/v1'

// ─── Fixtures ────────────────────────────────────────────────────────────────

export const UPLOAD_RES: UploadResponse = {
  upload_id: 'upl_test001',
  filename: 'DE_AP_Wave1.xlsx',
  size_bytes: 102400,
  detected_format: 'XLSX',
  status: 'uploaded',
}

export const RUN_RES: RunResponse = {
  batch_id: 'bat_test001',
  upload_id: 'upl_test001',
  status: 'queued',
  websocket_url: '/api/v1/ws/progress/bat_test001',
}

export const RESULTS_RES: ResultsResponse = {
  batch_id: 'bat_test001',
  status: 'complete',
  total: 3,
  page: 1,
  limit: 25,
  results: [
    {
      atom_id: 'REQ-AP-001',
      requirement_text: 'Three-way matching for AP invoices',
      classification: 'FIT',
      confidence: 0.94,
      d365_capability: 'Invoice Matching Policies',
      d365_navigation: 'AP > Invoices > Invoice matching',
      rationale: 'D365 F&O supports three-way matching natively.',
      module: 'AccountsPayable',
      country: 'DE',
      wave: 1,
      reviewer_override: false,
      evidence: {
        top_capability_score: 0.94,
        retrieval_confidence: 'HIGH',
        prior_fitments: [],
        candidates: [{ name: 'Invoice Matching Policies', score: 0.94, navigation: 'AP > Invoices > Invoice matching' }],
        route: 'FAST_TRACK',
        anomaly_flags: [],
        signal_breakdown: { embedding_cosine: 0.94 },
      },
      caveats: null,
      route_used: 'FAST_TRACK',
      config_steps: null,
      configuration_steps: null,
      gap_description: null,
      dev_effort: null,
      gap_type: null,
      journey: null,
    },
    {
      atom_id: 'REQ-AP-002',
      requirement_text: 'Custom vendor scorecard',
      classification: 'GAP',
      confidence: 0.58,
      d365_capability: 'Vendor Evaluation',
      d365_navigation: 'AP > Vendors > Evaluation',
      rationale: 'No standard composite scoring.',
      module: 'AccountsPayable',
      country: 'DE',
      wave: 1,
      reviewer_override: true,
      evidence: {
        top_capability_score: 0.58,
        retrieval_confidence: 'LOW',
        prior_fitments: [{ wave: 1, country: 'FR', classification: 'PARTIAL_FIT' }],
        candidates: [{ name: 'Vendor Evaluation', score: 0.58, navigation: 'AP > Vendors > Evaluation' }],
        route: 'GAP_CONFIRM',
        anomaly_flags: [],
        signal_breakdown: { embedding_cosine: 0.58 },
      },
      caveats: 'No standard composite scoring available.',
      route_used: 'GAP_CONFIRM',
      config_steps: null,
      configuration_steps: null,
      gap_description: 'Custom vendor scorecard requires X++ development',
      dev_effort: 'M',
      gap_type: 'Custom Development',
      journey: null,
    },
    {
      atom_id: 'REQ-GL-001',
      requirement_text: 'Multi-currency journal posting',
      classification: 'PARTIAL_FIT',
      confidence: 0.72,
      d365_capability: 'Currency Management',
      d365_navigation: 'GL > Journals > General',
      rationale: 'Partial support with configuration.',
      module: 'GeneralLedger',
      country: 'DE',
      wave: 1,
      reviewer_override: false,
      evidence: {
        top_capability_score: 0.72,
        retrieval_confidence: 'MEDIUM',
        prior_fitments: [],
        candidates: [{ name: 'Currency Management', score: 0.72, navigation: 'GL > Journals > General' }],
        route: 'DEEP_REASON',
        anomaly_flags: [],
        signal_breakdown: { embedding_cosine: 0.72 },
      },
      caveats: null,
      route_used: 'DEEP_REASON',
      config_steps: 'Configure currency revaluation journal with appropriate exchange rate variance accounts.',
      configuration_steps: ['Set up currency revaluation journal', 'Define exchange rate variance accounts'],
      gap_description: null,
      dev_effort: null,
      gap_type: null,
      journey: null,
    },
  ],
  summary: {
    fit: 1,
    partial_fit: 1,
    gap: 1,
    by_module: {
      AccountsPayable: { fit: 1, partial_fit: 0, gap: 1 },
      GeneralLedger: { fit: 0, partial_fit: 1, gap: 0 },
    },
  },
}

export const REVIEW_RES: ReviewResponse = {
  batch_id: 'bat_test001',
  status: 'review_pending',
  items: [
    {
      atom_id: 'REQ-AP-055',
      requirement_text: 'Custom vendor scorecard with weighted multi-factor rating',
      ai_classification: 'GAP',
      ai_confidence: 0.58,
      ai_rationale: 'No standard composite scoring in D365.',
      review_reason: 'low_confidence',
      evidence: {
        capabilities: [{ name: 'Vendor Evaluation', score: 0.58, navigation: 'AP > Vendors' }],
        prior_fitments: [],
        anomaly_flags: [],
      },
    },
  ],
}

export const REVIEW_SUBMIT_RES: ReviewSubmitResponse = {
  atom_id: 'REQ-AP-055',
  final_classification: 'GAP',
  reviewer_override: false,
  remaining_reviews: 0,
}

export const BATCHES_RES: BatchesResponse = {
  batches: [
    {
      batch_id: 'bat_test001',
      upload_filename: 'DE_AP_Wave1.xlsx',
      country: 'DE',
      wave: 1,
      status: 'complete',
      summary: { fit: 37, partial_fit: 7, gap: 6 },
      created_at: '2026-03-19T14:20:00Z',
      completed_at: '2026-03-19T14:22:00Z',
    },
    {
      batch_id: 'bat_test002',
      upload_filename: 'FR_GL_Wave2.xlsx',
      country: 'FR',
      wave: 2,
      status: 'running',
      summary: { fit: 0, partial_fit: 0, gap: 0 },
      created_at: '2026-03-20T09:00:00Z',
      completed_at: null,
    },
  ],
  total: 2,
  page: 1,
  limit: 10,
}

// ─── Handlers ────────────────────────────────────────────────────────────────

export const handlers = [
  http.post(`${BASE}/upload`, () => HttpResponse.json(UPLOAD_RES, { status: 201 })),
  http.post(`${BASE}/d365_fo/dynafit/run`, () => HttpResponse.json(RUN_RES, { status: 202 })),
  http.get(`${BASE}/d365_fo/dynafit/:batchId/results`, () =>
    HttpResponse.json(RESULTS_RES),
  ),
  http.get(`${BASE}/d365_fo/dynafit/:batchId/review`, () =>
    HttpResponse.json(REVIEW_RES),
  ),
  http.post(`${BASE}/d365_fo/dynafit/:batchId/review/:atomId`, () =>
    HttpResponse.json(REVIEW_SUBMIT_RES),
  ),
  http.post(`${BASE}/d365_fo/dynafit/:batchId/review/complete`, () =>
    HttpResponse.json({ status: 'resumed', batch_id: 'bat_test001' }),
  ),
  http.get(`${BASE}/d365_fo/dynafit/batches`, () => HttpResponse.json(BATCHES_RES)),
]
