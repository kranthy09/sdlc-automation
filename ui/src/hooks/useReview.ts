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

  const bulkApprove = useMutation({
    mutationFn: async (atomIds: string[]) => {
      const results = await Promise.allSettled(
        atomIds.map((atomId) =>
          submitReview(batchId, atomId, {
            decision: 'APPROVE',
            reviewer: 'reviewer@enterprise.ai',
          }),
        ),
      )
      const failed = results.filter((r) => r.status === 'rejected')
      if (failed.length > 0) {
        throw new Error(`${failed.length} of ${atomIds.length} approvals failed`)
      }
      return results
    },
    onSuccess: (_data, atomIds) => {
      qc.invalidateQueries({ queryKey: ['review', batchId] })
      addNotification({
        type: 'success',
        message: `Bulk approved ${atomIds.length} items`,
      })
    },
    onError: (err) =>
      addNotification({
        type: 'error',
        message: err instanceof Error ? err.message : 'Bulk approve failed',
      }),
  })

  return { query, submit, bulkApprove }
}
