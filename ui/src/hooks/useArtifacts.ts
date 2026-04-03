import { useQuery } from '@tanstack/react-query'
import { getArtifacts } from '@/api/dynafit'

/**
 * Hook to fetch artifacts for a batch.
 * Artifacts are immutable once written, so they are cached for 5 minutes.
 * Silently fails on 404 (old pipeline path that didn't use the new ingestion pipeline).
 */
export function useArtifacts(batchId: string | undefined) {
  return useQuery({
    queryKey: ['artifacts', batchId],
    queryFn: () => getArtifacts(batchId!),
    enabled: !!batchId,
    staleTime: 5 * 60 * 1000,  // artifacts are immutable
    retry: false,               // 404 = old pipeline path, suppress silently
    meta: { silent: true },     // don't show global error toast for artifacts
  })
}
