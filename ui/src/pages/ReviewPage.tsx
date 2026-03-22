import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { ReviewCard } from '@/components/review/ReviewCard'
import { ReviewProgress } from '@/components/review/ReviewProgress'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { useReview } from '@/hooks/useReview'
import { apiClient } from '@/api/client'
import { useUIStore } from '@/stores/uiStore'
import type { Classification, ReviewDecision } from '@/api/types'

export default function ReviewPage() {
  const { batchId } = useParams<{ batchId: string }>()
  const navigate = useNavigate()
  const { addNotification } = useUIStore()
  const { query, submit } = useReview(batchId!)
  const [submittingAtom, setSubmittingAtom] = useState<string | null>(null)
  const [completing, setCompleting] = useState(false)
  const [decidedIds, setDecidedIds] = useState<Set<string>>(new Set())
  const [showAutoApproved, setShowAutoApproved] = useState(false)

  const items = query.data?.items ?? []
  const autoApproved = query.data?.auto_approved ?? []
  const pendingItems = items.filter((i) => !decidedIds.has(i.atom_id))
  const reviewed = decidedIds.size

  const handleDecide = async (
    atomId: string,
    decision: ReviewDecision,
    overrideClass?: Classification,
    reason?: string,
  ) => {
    setSubmittingAtom(atomId)
    try {
      await submit.mutateAsync({
        atomId,
        req: {
          decision,
          override_classification: overrideClass ?? null,
          reason: reason ?? '',
          reviewer: 'reviewer@enterprise.ai',
        },
      })
      setDecidedIds((prev) => new Set(prev).add(atomId))
      addNotification({ type: 'success', message: `${atomId} — ${decision.toLowerCase()}d` })
    } finally {
      setSubmittingAtom(null)
    }
  }

  const handleComplete = async () => {
    setCompleting(true)
    try {
      await apiClient.post(`/d365_fo/dynafit/${batchId}/review/complete`)
      addNotification({ type: 'success', message: 'Reviews submitted — pipeline resuming…' })
      navigate(`/progress/${batchId}`)
    } catch {
      addNotification({ type: 'error', message: 'Failed to complete reviews.' })
    } finally {
      setCompleting(false)
    }
  }

  const allReviewed = items.length > 0 && reviewed === items.length

  return (
    <div>
      <PageHeader
        title="Human Review Queue"
        description={`Batch ${batchId} — items flagged for review`}
        action={
          allReviewed ? (
            <Button size="sm" onClick={handleComplete} loading={completing}>
              Submit &amp; resume pipeline
            </Button>
          ) : undefined
        }
      />

      <div className="space-y-4 px-6 pb-6 max-w-3xl">
        {/* Progress */}
        {items.length > 0 && (
          <ReviewProgress reviewed={reviewed} total={items.length} />
        )}

        {/* Cards */}
        {query.isLoading ? (
          Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))
        ) : pendingItems.length === 0 && !allReviewed ? (
          <p className="text-sm text-text-muted">No items pending review.</p>
        ) : allReviewed ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-fit/30 bg-fit-muted/10 py-10">
            <p className="text-sm font-medium text-fit-text">All {items.length} items reviewed</p>
            <Button onClick={handleComplete} loading={completing}>
              Submit &amp; resume pipeline
            </Button>
          </div>
        ) : (
          pendingItems.map((item) => (
            <ReviewCard
              key={item.atom_id}
              item={item}
              submitting={submittingAtom === item.atom_id}
              onDecide={(decision, overrideClass, reason) =>
                handleDecide(item.atom_id, decision, overrideClass, reason)
              }
            />
          ))
        )}

        {/* Auto-approved items (collapsible) */}
        {autoApproved.length > 0 && (
          <div className="mt-6 rounded-xl border border-bg-border bg-bg-raised/50">
            <button
              type="button"
              className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-text-secondary hover:text-text-primary"
              onClick={() => setShowAutoApproved((v) => !v)}
            >
              <span>Auto-approved items ({autoApproved.length})</span>
              <span className={`transition-transform ${showAutoApproved ? 'rotate-180' : ''}`}>
                ▼
              </span>
            </button>
            {showAutoApproved && (
              <div className="border-t border-bg-border">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-bg-border text-text-muted">
                      <th className="px-4 py-2 font-medium">Atom</th>
                      <th className="px-4 py-2 font-medium">Requirement</th>
                      <th className="px-4 py-2 font-medium">Module</th>
                      <th className="px-4 py-2 font-medium">Classification</th>
                      <th className="px-4 py-2 font-medium text-right">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {autoApproved.map((item) => (
                      <tr key={item.atom_id} className="border-b border-bg-border/50">
                        <td className="px-4 py-2 font-mono text-text-muted">{item.atom_id}</td>
                        <td className="max-w-xs truncate px-4 py-2 text-text-primary">{item.requirement_text}</td>
                        <td className="px-4 py-2 text-text-secondary">{item.module}</td>
                        <td className="px-4 py-2">
                          <Badge variant={item.classification as Classification} />
                        </td>
                        <td className="px-4 py-2 text-right text-text-secondary">
                          {(item.confidence * 100).toFixed(0)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
