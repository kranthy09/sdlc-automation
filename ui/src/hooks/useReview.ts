import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getReview, submitReview } from '@/api/dynafit'
import type { ReviewSubmitRequest } from '@/api/types'
import { useUIStore } from '@/stores/uiStore'

export function useReview(batchId: string) {
  const qc = useQueryClient()
  const { addNotification } = useUIStore()

  const query = useQuery({
    queryKey: ['review', batchId],
    queryFn: () => getReview(batchId),
    enabled: !!batchId,
  })

  const submit = useMutation({
    mutationFn: ({ atomId, req }: { atomId: string; req: ReviewSubmitRequest }) =>
      submitReview(batchId, atomId, req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review', batchId] })
    },
    onError: () =>
      addNotification({ type: 'error', message: 'Failed to submit review decision.' }),
  })

  return { query, submit }
}
