import { useQuery } from '@tanstack/react-query'
import { getResults } from '@/api/dynafit'
import type { ResultsQuery } from '@/api/types'

export function useResults(batchId: string, query: ResultsQuery = {}) {
  return useQuery({
    queryKey: ['results', batchId, query],
    queryFn: () => getResults(batchId, query),
    enabled: !!batchId,
    staleTime: 30_000,
  })
}
