import { useQuery } from '@tanstack/react-query'
import { getJourney } from '@/api/dynafit'

export function useJourney(batchId: string, atomId?: string) {
  return useQuery({
    queryKey: ['journey', batchId, atomId],
    queryFn: () => getJourney(batchId, atomId),
    enabled: !!batchId && !!atomId,
    staleTime: 60_000,
  })
}
