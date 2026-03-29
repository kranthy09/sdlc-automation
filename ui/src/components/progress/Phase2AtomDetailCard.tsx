import { useEffect, useState } from 'react'
import { ExternalLink, Loader, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import { getJourney } from '@/api/dynafit'
import { ApiError } from '@/api/client'
import type { Phase2ContextRow, AtomJourney } from '@/api/types'

interface Phase2AtomDetailCardProps {
  atom: Phase2ContextRow | null
  batchId: string
}

const getConfidenceColor = (confidence: 'HIGH' | 'MEDIUM' | 'LOW'): string => {
  switch (confidence) {
    case 'HIGH':
      return 'bg-fit-muted text-fit-text border-fit'
    case 'MEDIUM':
      return 'bg-partial-muted text-partial-text border-partial'
    case 'LOW':
      return 'bg-gap-muted text-gap-text border-gap'
  }
}

const getScoreColor = (score: number): string => {
  if (score >= 0.7) return 'text-fit-text'
  if (score >= 0.4) return 'text-partial-text'
  return 'text-gap-text'
}

export function Phase2AtomDetailCard({
  atom,
  batchId,
}: Phase2AtomDetailCardProps) {
  const [journey, setJourney] = useState<AtomJourney | null>(null)
  const [loading, setLoading] = useState(false)
  // null = not fetched, 'pending' = batch not completed yet, string = real error
  const [journeyState, setJourneyState] = useState<null | 'pending' | string>(null)

  useEffect(() => {
    if (!atom) return

    setJourney(null)
    setJourneyState(null)

    ;(async () => {
      try {
        setLoading(true)
        const resp = await getJourney(batchId, atom.atom_id)
        if (resp.atoms && resp.atoms.length > 0) {
          setJourney(resp.atoms[0])
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setJourneyState('pending')
        } else {
          setJourneyState(err instanceof Error ? err.message : 'Failed to load retrieval details')
        }
      } finally {
        setLoading(false)
      }
    })()
  }, [atom, batchId])

  if (!atom) {
    return (
      <div className="rounded-lg border border-bg-border bg-bg-surface/50 p-6">
        <p className="text-sm text-text-muted">No atom selected</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-bg-border bg-bg-surface/50 p-6 space-y-6">
      {/* Requirement Text */}
      <div>
        <h3 className="text-sm font-semibold text-text-primary mb-3">Requirement</h3>
        <p className="text-sm text-text-secondary leading-relaxed whitespace-pre-wrap break-words">
          {atom.requirement_text}
        </p>
      </div>

      {/* Metadata Grid — sourced from gate data, always available */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-text-primary">Metadata</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Atom ID</p>
            <p className="text-sm font-mono text-text-secondary">{atom.atom_id}</p>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Module</p>
            <p className="text-sm text-text-secondary font-medium">{atom.module || '—'}</p>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Country</p>
            <p className="text-sm text-text-secondary">{atom.country || '—'}</p>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Intent</p>
            <p className="text-sm text-text-secondary">{atom.intent || '—'}</p>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Priority</p>
            <p className="text-sm text-text-secondary">{atom.priority || '—'}</p>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Retrieval Confidence</p>
            <span className={cn(
              'inline-block px-2 py-0.5 rounded text-xs font-medium border',
              getConfidenceColor(atom.retrieval_confidence)
            )}>
              {atom.retrieval_confidence}
            </span>
          </div>
          {atom.top_capability && (
            <div className="col-span-2 rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Top Capability</p>
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm text-text-secondary truncate">{atom.top_capability}</p>
                <p className={cn('text-sm font-bold shrink-0', getScoreColor(atom.top_capability_score))}>
                  {Math.round(atom.top_capability_score * 100)}%
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Detailed Retrieval Data — requires journey endpoint (completed batches only) */}
      {loading ? (
        <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-6 flex items-center justify-center gap-2">
          <Loader className="h-4 w-4 animate-spin text-text-muted" />
          <p className="text-sm text-text-muted">Loading retrieval details...</p>
        </div>
      ) : journeyState === 'pending' ? (
        <div className="rounded-lg border border-accent/20 bg-accent/5 px-4 py-3 flex items-start gap-2">
          <Clock className="h-4 w-4 text-accent-glow shrink-0 mt-0.5" />
          <p className="text-sm text-text-secondary">
            Full retrieval details (capabilities, references, prior fitments) available after batch completes.
          </p>
        </div>
      ) : journeyState ? (
        <div className="rounded-lg border border-gap/30 bg-gap-muted/5 px-4 py-3">
          <p className="text-sm text-gap-text">{journeyState}</p>
        </div>
      ) : journey?.retrieve ? (
        <div className="space-y-4">
          {/* Capabilities */}
          {journey.retrieve.capabilities && journey.retrieve.capabilities.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                Retrieved Capabilities ({journey.retrieve.capabilities.length})
              </h3>
              <div className="space-y-2">
                {journey.retrieve.capabilities.map((cap, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border border-bg-border bg-bg-raised p-3 flex items-start justify-between gap-3"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-text-primary truncate" title={cap.name}>
                        {cap.name}
                      </p>
                      {cap.navigation && (
                        <p className="text-xs text-text-secondary mt-1 font-mono truncate" title={cap.navigation}>
                          {cap.navigation}
                        </p>
                      )}
                    </div>
                    <div className="shrink-0">
                      <p className={cn('text-sm font-bold', getScoreColor(cap.score))}>
                        {Math.round(cap.score * 100)}%
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* MS Learn References */}
          {journey.retrieve.ms_learn_refs && journey.retrieve.ms_learn_refs.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                MS Learn References ({journey.retrieve.ms_learn_refs.length})
              </h3>
              <div className="space-y-2">
                {journey.retrieve.ms_learn_refs.map((ref, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border border-bg-border bg-bg-raised p-3 flex items-start justify-between gap-3"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-text-secondary truncate" title={ref.title}>
                        {ref.title}
                      </p>
                    </div>
                    <div className="shrink-0">
                      <p className={cn('text-sm font-bold', getScoreColor(ref.score))}>
                        {Math.round(ref.score * 100)}%
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Prior Fitments */}
          {journey.retrieve.prior_fitments && journey.retrieve.prior_fitments.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                Prior Fitments ({journey.retrieve.prior_fitments.length})
              </h3>
              <div className="space-y-2">
                {journey.retrieve.prior_fitments.map((fitment, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border border-bg-border bg-bg-raised p-3 flex items-center justify-between"
                  >
                    <div className="flex-1">
                      <p className="text-sm font-medium text-text-primary">
                        Wave {fitment.wave} — {fitment.country}
                      </p>
                      <p className="text-xs text-text-secondary mt-0.5">
                        Classification: <span className="font-mono">{fitment.classification}</span>
                      </p>
                    </div>
                    <Badge
                      variant="default"
                      label={fitment.classification}
                      className="ml-2 shrink-0"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : null}

      {/* Summary Info Banner */}
      <div className="rounded-lg border border-accent/20 bg-accent/5 p-4 flex gap-3">
        <ExternalLink className="h-4 w-4 text-accent-glow shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="text-xs font-medium text-text-primary mb-1">Retrieval Augmented Generation</p>
          <p className="text-xs text-text-secondary leading-relaxed">
            Phase 2 retrieves similar D365 capabilities and historical fitments from the knowledge base to support the classification phase. Higher confidence and capability scores indicate stronger matches.
          </p>
        </div>
      </div>
    </div>
  )
}
