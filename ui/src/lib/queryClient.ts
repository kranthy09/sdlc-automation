import { MutationCache, QueryCache, QueryClient, type Query } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import { useUIStore } from '@/stores/uiStore'

function handleError(err: unknown, query?: Query): void {
  // Skip error toast for queries marked as silent (e.g., optional artifact fetches)
  if (query?.meta?.silent) return

  const msg =
    err instanceof ApiError
      ? err.message
      : err instanceof Error
        ? err.message
        : 'An unexpected error occurred'

  useUIStore.getState().addNotification({ type: 'error', message: msg })
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,        // 30s — results tables don't need to refetch constantly
      gcTime: 5 * 60 * 1_000,  // 5min GC
      retry: (failureCount, err) => {
        // Don't retry 4xx client errors
        if (err instanceof ApiError && (err.status ?? 0) < 500) return false
        return failureCount < 2
      },
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
  queryCache: new QueryCache({
    onError: (err, query) => handleError(err, query),
  }),
  mutationCache: new MutationCache({
    onError: handleError,
  }),
})
