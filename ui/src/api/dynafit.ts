import { apiClient } from './client'
import type {
  BatchesQuery,
  BatchesResponse,
  ResultsQuery,
  ResultsResponse,
  ReviewResponse,
  ReviewSubmitRequest,
  ReviewSubmitResponse,
  RunRequest,
  RunResponse,
  UploadRequest,
  UploadResponse,
} from './types'

// ─── 1. Upload file ───────────────────────────────────────────────────────────
export async function uploadFile(req: UploadRequest): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', req.file)
  form.append('product', req.product)
  form.append('country', req.country)
  form.append('wave', String(req.wave))

  const res = await apiClient.post<UploadResponse>('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

// ─── 2. Start analysis ────────────────────────────────────────────────────────
export async function runAnalysis(req: RunRequest): Promise<RunResponse> {
  const res = await apiClient.post<RunResponse>('/d365_fo/dynafit/run', req)
  return res.data
}

// ─── 3. Get results ───────────────────────────────────────────────────────────
export async function getResults(
  batchId: string,
  query: ResultsQuery = {},
): Promise<ResultsResponse> {
  const res = await apiClient.get<ResultsResponse>(`/d365_fo/dynafit/${batchId}/results`, {
    params: query,
  })
  return res.data
}

// ─── 4. Get review queue ──────────────────────────────────────────────────────
export async function getReview(batchId: string): Promise<ReviewResponse> {
  const res = await apiClient.get<ReviewResponse>(`/d365_fo/dynafit/${batchId}/review`)
  return res.data
}

// ─── 5. Submit review decision ────────────────────────────────────────────────
export async function submitReview(
  batchId: string,
  atomId: string,
  req: ReviewSubmitRequest,
): Promise<ReviewSubmitResponse> {
  const res = await apiClient.post<ReviewSubmitResponse>(
    `/d365_fo/dynafit/${batchId}/review/${atomId}`,
    req,
  )
  return res.data
}

// ─── 6. Download report ───────────────────────────────────────────────────────
export function getReportUrl(batchId: string): string {
  const base = import.meta.env.VITE_API_URL ?? '/api/v1'
  return `${base}/d365_fo/dynafit/${batchId}/report`
}

export async function downloadReport(batchId: string): Promise<Blob> {
  const res = await apiClient.get<Blob>(`/d365_fo/dynafit/${batchId}/report`, {
    responseType: 'blob',
    headers: {
      Accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    },
  })
  return res.data
}

// ─── 7. Batch history ─────────────────────────────────────────────────────────
export async function getBatches(query: BatchesQuery = {}): Promise<BatchesResponse> {
  const res = await apiClient.get<BatchesResponse>('/d365_fo/dynafit/batches', { params: query })
  return res.data
}
