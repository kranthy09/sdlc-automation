import { useQueries } from '@tanstack/react-query'
import { getResults } from '@/api/dynafit'
import type { ResultsResponse } from '@/api/types'

interface UseComparisonOptions {
  batchId1?: string
  batchId2?: string
}

export function useComparison({ batchId1, batchId2 }: UseComparisonOptions) {
  const queries = useQueries({
    queries: [
      {
        queryKey: ['results', batchId1],
        queryFn: () => getResults(batchId1!, { limit: 1000 }),
        enabled: !!batchId1,
        staleTime: 60_000,
      },
      {
        queryKey: ['results', batchId2],
        queryFn: () => getResults(batchId2!, { limit: 1000 }),
        enabled: !!batchId2,
        staleTime: 60_000,
      },
    ],
  })

  const [data1, data2] = queries
  const isLoading = data1.isLoading || data2.isLoading
  const isError = data1.isError || data2.isError

  // Compute comparison stats
  const comparison = data1.data && data2.data ? {
    batch1: data1.data,
    batch2: data2.data,
    fitDiff: data2.data.summary.fit - data1.data.summary.fit,
    partialDiff: data2.data.summary.partial_fit - data1.data.summary.partial_fit,
    gapDiff: data2.data.summary.gap - data1.data.summary.gap,
    confidenceDiff: {
      avg1: data1.data.results.length > 0
        ? data1.data.results.reduce((sum, r) => sum + r.confidence, 0) / data1.data.results.length
        : 0,
      avg2: data2.data.results.length > 0
        ? data2.data.results.reduce((sum, r) => sum + r.confidence, 0) / data2.data.results.length
        : 0,
    },
  } : null

  return { data1: data1.data, data2: data2.data, comparison, isLoading, isError }
}
