import axios, { type AxiosError, type AxiosResponse } from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL ?? '/api/v1'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

// ─── Request interceptor — attach correlation ID ──────────────────────────────
apiClient.interceptors.request.use((config) => {
  config.headers['X-Request-ID'] = crypto.randomUUID()
  return config
})

// ─── Response interceptor — unwrap data, normalize errors ────────────────────
apiClient.interceptors.response.use(
  (res: AxiosResponse) => res,
  (err: AxiosError<{ detail?: string; message?: string }>) => {
    const status = err.response?.status
    const detail =
      err.response?.data?.detail ??
      err.response?.data?.message ??
      err.message ??
      'An unexpected error occurred'

    const normalized = new ApiError(detail, status)
    return Promise.reject(normalized)
  },
)

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get isNotFound() {
    return this.status === 404
  }

  get isServerError() {
    return (this.status ?? 0) >= 500
  }
}
