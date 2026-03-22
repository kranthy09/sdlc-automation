import { useQuery } from '@tanstack/react-query'
import { getBatches } from '@/api/dynafit'
import type { BatchesQuery } from '@/api/types'

export function useBatches(query: BatchesQuery = {}) {
  return useQuery({
    queryKey: ['batches', query],
    queryFn: () => getBatches(query),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}
