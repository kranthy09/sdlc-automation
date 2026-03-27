import { useQuery } from '@tanstack/react-query'
import { getJourney } from '@/api/dynafit'

export function useBatchJourney(batchId: string) {
  return useQuery({
    queryKey: ['journey', batchId],
    queryFn: () => getJourney(batchId),
    enabled: !!batchId,
    staleTime: 60_000,
  })
}
