import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ChevronRight, Wrench, Code2, CheckCircle2 } from 'lucide-react'
import { cn, formatConfidence, confidenceTier, CONFIDENCE_TIER_COLOR } from '@/lib/utils'
import { PageHeader } from '@/components/layout/PageHeader'
import { ReviewCard } from '@/components/review/ReviewCard'
import { ReviewProgress } from '@/components/review/ReviewProgress'
import { ReviewTabs, type ReviewTabValue } from '@/components/review/ReviewTabs'
import { BulkActions } from '@/components/review/BulkActions'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { useReview } from '@/hooks/useReview'
import { apiClient } from '@/api/client'
import { useUIStore } from '@/stores/uiStore'
import type { AutoApprovedItem, Classification, ReviewDecision, ReviewItem } from '@/api/types'

const DEV_EFFORT_LABEL: Record<string, string> = { S: 'Small', M: 'Medium', L: 'Large' }
const DEV_EFFORT_COLOR: Record<string, string> = {
  S: 'bg-fit-muted text-fit-text border-fit/30',
  M: 'bg-partial-muted text-partial-text border-partial/30',
  L: 'bg-gap-muted text-gap-text border-gap/30',
}

function AutoApprovedRow({ item }: { item: AutoApprovedItem }) {
  const [open, setOpen] = useState(false)
  const tier = confidenceTier(item.confidence)

  return (
    <>
      <tr
        className="border-b border-bg-border/50 cursor-pointer hover:bg-bg-raised/50 transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        <td className="px-2 py-2">
          <ChevronRight
            className={cn('h-3.5 w-3.5 text-text-muted transition-transform', open && 'rotate-90')}
          />
        </td>
        <td className="px-4 py-2 font-mono text-text-muted">{item.atom_id}</td>
        <td className="px-4 py-2 text-sm leading-relaxed text-text-primary">{item.requirement_text}</td>
        <td className="px-4 py-2 text-text-secondary">{item.module}</td>
        <td className="px-4 py-2 flex items-center gap-2">
          <Badge variant={item.classification} />
          <span className="inline-flex px-2 py-0.5 rounded-full border border-fit/30 bg-fit-muted/30 text-[10px] font-medium text-fit-text">
            Auto-approved
          </span>
        </td>
        <td className={cn('px-4 py-2 text-right font-medium', CONFIDENCE_TIER_COLOR[tier])}>
          {formatConfidence(item.confidence)}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6} className="bg-bg-raised/30 px-6 py-4 animate-fade-in">
            <div className="max-w-4xl space-y-4" style={{ wordBreak: 'break-word' }}>
              {/* Rationale */}
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-text-muted mb-1">
                  AI Rationale
                </p>
                <blockquote className="border-l-2 border-bg-border pl-3 text-sm italic text-text-secondary leading-relaxed">
                  {item.rationale}
                </blockquote>
              </div>

              {/* D365 capability + navigation */}
              {item.d365_capability && (
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-text-muted mb-1">
                    D365 Capability
                  </p>
                  <p className="text-sm text-text-primary">{item.d365_capability}</p>
                  {item.d365_navigation && (
                    <p className="font-mono text-xs text-accent-glow mt-0.5">{item.d365_navigation}</p>
                  )}
                </div>
              )}

              {/* MS Learn References */}
              {item.evidence && (item.evidence.ms_learn_refs?.length ?? 0) > 0 && (
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-text-muted mb-2">
                    MS Learn references
                  </p>
                  <div className="space-y-1.5">
                    {item.evidence.ms_learn_refs.map((ref, i) => (
                      <div key={i} className="flex items-center justify-between">
                        <p className="text-sm text-text-primary">{ref.title}</p>
                        <span className="text-sm font-semibold text-text-secondary">
                          {formatConfidence(ref.score)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* PARTIAL_FIT: Configuration steps — always render the block so missing data is explicit */}
              {item.classification === 'PARTIAL_FIT' && (
                <div className="rounded-lg border border-partial/20 bg-partial-muted/10 p-3">
                  <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-partial-text">
                    <Wrench className="h-3.5 w-3.5" />
                    Configuration Steps
                  </div>
                  {item.configuration_steps && item.configuration_steps.length > 0 ? (
                    <ol className="space-y-1 pl-5 list-decimal text-sm text-text-primary">
                      {item.configuration_steps.map((step, i) => (
                        <li key={i}>{step}</li>
                      ))}
                    </ol>
                  ) : item.config_steps ? (
                    <p className="text-sm text-text-primary whitespace-pre-line">{item.config_steps}</p>
                  ) : (
                    <div className="space-y-2">
                      <p className="text-xs text-text-muted italic">
                        The LLM classified this as PARTIAL_FIT (the D365 capability <strong>{item.d365_capability || 'N/A'}</strong> is relevant) but did not generate specific configuration steps.
                      </p>
                      {item.caveats && (
                        <div className="rounded-md bg-bg-raised/50 p-2 border border-bg-border">
                          <p className="text-xs text-text-muted mb-1 font-medium">LLM Notes:</p>
                          <p className="text-xs text-text-secondary">{item.caveats}</p>
                        </div>
                      )}
                      <p className="text-xs text-text-muted">
                        Refer to the D365 capability specification and MS Learn documentation for configuration guidance. This item requires analyst review or manual configuration specification.
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* GAP: Dev effort + gap type + gap description */}
              {item.classification === 'GAP' && (item.dev_effort || item.gap_type || item.gap_description) && (
                <div className="rounded-lg border border-gap/20 bg-gap-muted/10 p-3">
                  <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-gap-text">
                    <Code2 className="h-3.5 w-3.5" />
                    Gap Details
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {item.dev_effort && (
                      <span
                        className={cn(
                          'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold',
                          DEV_EFFORT_COLOR[item.dev_effort],
                        )}
                      >
                        Effort: {DEV_EFFORT_LABEL[item.dev_effort] ?? item.dev_effort}
                      </span>
                    )}
                    {item.gap_type && (
                      <span className="inline-flex items-center rounded-full border border-bg-border bg-bg-raised px-2.5 py-0.5 text-xs font-medium text-text-secondary">
                        {item.gap_type}
                      </span>
                    )}
                  </div>
                  {item.gap_description && (
                    <p className="mt-2 text-sm text-text-secondary">{item.gap_description}</p>
                  )}
                </div>
              )}

              {/* FIT: simple confirmation */}
              {item.classification === 'FIT' && (
                <div className="rounded-lg border border-fit/20 bg-fit-muted/10 p-3">
                  <p className="text-xs font-medium text-fit-text">
                    Full fit — no configuration or customization required
                  </p>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default function ReviewPage() {
  const { batchId } = useParams<{ batchId: string }>()
  const navigate = useNavigate()
  const { addNotification } = useUIStore()
  const { query, submit, bulkApprove } = useReview(batchId!)
  const [submittingAtom, setSubmittingAtom] = useState<string | null>(null)
  const [completing, setCompleting] = useState(false)
  const [decidedIds, setDecidedIds] = useState<Set<string>>(new Set())
  const [showAutoApproved, setShowAutoApproved] = useState(false)
  const [activeTab, setActiveTab] = useState<ReviewTabValue>('ALL')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const items = query.data?.items ?? []
  const autoApproved = query.data?.auto_approved ?? []
  // An item is pending when neither the server nor this session has recorded a decision.
  // Using server-side `reviewed` means the page survives navigation and remount correctly.
  const pendingItems = items.filter((i) => !i.reviewed && !decidedIds.has(i.atom_id))

  // Group counts by classification (pending + auto-approved)
  const tabCounts = useMemo(() => {
    const counts = { ALL: 0, FIT: 0, PARTIAL_FIT: 0, GAP: 0 }
    for (const item of pendingItems) {
      counts.ALL++
      const cls = item.ai_classification as Classification
      if (cls in counts) counts[cls]++
    }
    for (const item of autoApproved) {
      counts.ALL++
      const cls = item.classification as Classification
      if (cls in counts) counts[cls]++
    }
    return counts
  }, [pendingItems, autoApproved])

  // Filter pending items by active tab
  const filteredItems = useMemo(() => {
    if (activeTab === 'ALL') return pendingItems
    return pendingItems.filter((i) => i.ai_classification === activeTab)
  }, [pendingItems, activeTab])

  // Filter auto-approved items by active tab
  const filteredAutoApproved = useMemo(() => {
    if (activeTab === 'ALL') return autoApproved
    return autoApproved.filter((i) => i.classification === activeTab)
  }, [autoApproved, activeTab])

  const reviewed = items.filter((i) => i.reviewed || decidedIds.has(i.atom_id)).length

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
      setSelectedIds((prev) => {
        const next = new Set(prev)
        next.delete(atomId)
        return next
      })
      addNotification({ type: 'success', message: `${atomId} — ${decision.toLowerCase()}d` })
    } finally {
      setSubmittingAtom(null)
    }
  }

  const handleBulkApprove = async () => {
    const ids = Array.from(selectedIds)
    await bulkApprove.mutateAsync(ids)
    setDecidedIds((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => next.add(id))
      return next
    })
    setSelectedIds(new Set())
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

  const toggleSelect = (atomId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(atomId)) next.delete(atomId)
      else next.add(atomId)
      return next
    })
  }

  const selectAllVisible = () => {
    setSelectedIds(new Set(filteredItems.map((i) => i.atom_id)))
  }

  const deselectAll = () => {
    setSelectedIds(new Set())
  }

  const allReviewed = items.length > 0 && items.every((i) => i.reviewed || decidedIds.has(i.atom_id))

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

      <div className="space-y-4 px-6 pb-6 max-w-6xl">
        {/* No items state */}
        {query.isLoaded && items.length === 0 && autoApproved.length === 0 && (
          <EmptyState
            icon={<CheckCircle2 className="h-12 w-12 text-fit-text" />}
            title="No items require review"
            description="All requirements have been processed and automatically approved."
            action={{
              label: 'View results',
              onClick: () => navigate(`/results/${batchId}`),
            }}
          />
        )}

        {/* Progress */}
        {items.length > 0 && (
          <ReviewProgress reviewed={reviewed} total={items.length} />
        )}

        {/* Tabs */}
        {(pendingItems.length > 0 || autoApproved.length > 0) && (
          <ReviewTabs
            tabs={[
              { value: 'ALL', label: 'All', count: tabCounts.ALL },
              { value: 'FIT', label: 'Fit', count: tabCounts.FIT },
              { value: 'PARTIAL_FIT', label: 'Partial Fit', count: tabCounts.PARTIAL_FIT },
              { value: 'GAP', label: 'Gap', count: tabCounts.GAP },
            ]}
            active={activeTab}
            onChange={setActiveTab}
          />
        )}

        {/* Bulk actions bar */}
        <BulkActions
          selectedCount={selectedIds.size}
          totalCount={filteredItems.length}
          onSelectAll={selectAllVisible}
          onDeselectAll={deselectAll}
          onBulkApprove={handleBulkApprove}
          loading={bulkApprove.isPending}
        />

        {/* Cards */}
        {query.isLoading ? (
          Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))
        ) : filteredItems.length === 0 && !allReviewed ? (
          <p className="text-sm text-text-muted">
            {activeTab === 'ALL'
              ? 'No items pending review.'
              : `No ${activeTab.replace('_', ' ').toLowerCase()} items pending review.`}
          </p>
        ) : allReviewed ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-fit/30 bg-fit-muted/10 py-10">
            <p className="text-sm font-medium text-fit-text">All {items.length} items reviewed</p>
            <Button onClick={handleComplete} loading={completing}>
              Submit &amp; resume pipeline
            </Button>
          </div>
        ) : (
          filteredItems.map((item) => (
            <ReviewCard
              key={item.atom_id}
              item={item}
              submitting={submittingAtom === item.atom_id}
              selected={selectedIds.has(item.atom_id)}
              onToggleSelect={() => toggleSelect(item.atom_id)}
              onDecide={(decision, overrideClass, reason) =>
                handleDecide(item.atom_id, decision, overrideClass, reason)
              }
            />
          ))
        )}

        {/* Auto-approved items (collapsible, filtered by tab) */}
        {filteredAutoApproved.length > 0 && (
          <div className="mt-6 rounded-xl border border-bg-border bg-bg-raised/50">
            <button
              type="button"
              className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-text-secondary hover:text-text-primary"
              onClick={() => setShowAutoApproved((v) => !v)}
            >
              <span>Auto-approved items ({filteredAutoApproved.length})</span>
              <span className={`transition-transform ${showAutoApproved ? 'rotate-180' : ''}`}>
                ▼
              </span>
            </button>
            {showAutoApproved && (
              <div className="border-t border-bg-border">
                <table className="w-full table-fixed text-left text-xs">
                  <colgroup>
                    <col className="w-8" />
                    <col className="w-32" />
                    <col />
                    <col className="w-36" />
                    <col className="w-28" />
                    <col className="w-20" />
                  </colgroup>
                  <thead>
                    <tr className="border-b border-bg-border text-text-muted">
                      <th className="px-2 py-2" />
                      <th className="px-4 py-2 font-medium">Atom</th>
                      <th className="px-4 py-2 font-medium">Requirement</th>
                      <th className="px-4 py-2 font-medium">Module</th>
                      <th className="px-4 py-2 font-medium">Classification</th>
                      <th className="px-4 py-2 font-medium text-right">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredAutoApproved.map((item) => (
                      <AutoApprovedRow key={item.atom_id} item={item} />
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
