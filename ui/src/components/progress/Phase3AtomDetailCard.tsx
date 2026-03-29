import { useEffect, useState } from 'react'
import { AlertCircle, Loader, Zap, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getJourney } from '@/api/dynafit'
import { ApiError } from '@/api/client'
import type { Phase3MatchRow, AtomJourney } from '@/api/types'

interface Phase3AtomDetailCardProps {
  atom: Phase3MatchRow | null
  batchId: string
}

const ROUTE_COLORS: Record<string, string> = {
  FAST_TRACK: 'bg-fit-muted text-fit-text border-fit',
  DEEP_REASON: 'bg-partial-muted text-partial-text border-partial',
  GAP_CONFIRM: 'bg-gap-muted text-gap-text border-gap',
}

const getSignalColor = (score: number): string => {
  if (score >= 0.85) return 'text-fit-text'
  if (score >= 0.60) return 'text-partial-text'
  return 'text-gap-text'
}

const getCompositeColor = (score: number): string => {
  if (score >= 0.85) return 'text-fit-text bg-fit-muted/10'
  if (score >= 0.60) return 'text-partial-text bg-partial-muted/10'
  return 'text-gap-text bg-gap-muted/10'
}

export function Phase3AtomDetailCard({
  atom,
  batchId,
}: Phase3AtomDetailCardProps) {
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
          setJourneyState(err instanceof Error ? err.message : 'Failed to load signal data')
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
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Priority</p>
            <p className="text-sm text-text-secondary">{atom.priority || '—'}</p>
          </div>
        </div>
      </div>

      {/* Route & Composite Score — from gate data */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-text-primary">Matching Results</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">Composite Score</p>
            <div className="flex items-baseline gap-2">
              <p className={cn('text-2xl font-bold', getCompositeColor(atom.composite_score))}>
                {Math.round(atom.composite_score * 100)}%
              </p>
              <p className="text-xs text-text-muted">out of 100</p>
            </div>
            <div className="mt-2 h-1.5 rounded-full bg-bg-border/30 overflow-hidden">
              <div
                className={cn(
                  'h-full transition-all',
                  atom.composite_score >= 0.85 ? 'bg-fit-text' :
                  atom.composite_score >= 0.60 ? 'bg-partial-text' :
                  'bg-gap-text'
                )}
                style={{ width: `${Math.min(atom.composite_score * 100, 100)}%` }}
              />
            </div>
          </div>

          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">Route</p>
            <div className="flex items-center">
              <span className={cn(
                'inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium border',
                ROUTE_COLORS[atom.route] || 'bg-bg-raised border-bg-border text-text-secondary'
              )}>
                {atom.route}
              </span>
            </div>
            <p className="text-xs text-text-muted mt-2 leading-relaxed">
              {atom.route === 'FAST_TRACK' && 'High confidence match with historical alignment'}
              {atom.route === 'DEEP_REASON' && 'Requires detailed LLM reasoning'}
              {atom.route === 'GAP_CONFIRM' && 'Below threshold, likely a gap'}
            </p>
          </div>
        </div>
      </div>

      {/* Anomaly Flags — from gate data (atom.anomaly_flags), always available */}
      {atom.anomaly_flags && atom.anomaly_flags.length > 0 ? (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <AlertCircle className="h-4 w-4 text-partial-text" />
            <h3 className="text-sm font-semibold text-text-primary">
              Anomalies Detected ({atom.anomaly_flags.length})
            </h3>
          </div>
          <div className="space-y-2">
            {atom.anomaly_flags.map((flag, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-partial/30 bg-partial-muted/10 p-3 flex gap-2"
              >
                <Zap className="h-4 w-4 text-partial-text shrink-0 mt-0.5" />
                <p className="text-xs text-partial-text leading-relaxed font-mono">
                  {flag}
                </p>
              </div>
            ))}
          </div>
          <p className="text-xs text-text-muted mt-2 leading-relaxed">
            Anomalies flag potential false positives: high semantic similarity without matching entities may indicate incorrect capability match.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-fit/30 bg-fit-muted/5 p-3 flex gap-2">
          <div className="h-2 w-2 rounded-full bg-fit-text shrink-0 mt-1" />
          <p className="text-xs text-fit-text">No anomalies detected. Signal scores are consistent.</p>
        </div>
      )}

      {/* Signal Breakdown — requires journey endpoint (completed batches only) */}
      {loading ? (
        <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-6 flex items-center justify-center gap-2">
          <Loader className="h-4 w-4 animate-spin text-text-muted" />
          <p className="text-sm text-text-muted">Loading signal analysis...</p>
        </div>
      ) : journeyState === 'pending' ? (
        <div className="rounded-lg border border-accent/20 bg-accent/5 px-4 py-3 flex items-start gap-2">
          <Clock className="h-4 w-4 text-accent-glow shrink-0 mt-0.5" />
          <p className="text-sm text-text-secondary">
            Detailed signal breakdown available after batch completes.
          </p>
        </div>
      ) : journeyState ? (
        <div className="rounded-lg border border-gap/30 bg-gap-muted/5 px-4 py-3">
          <p className="text-sm text-gap-text">{journeyState}</p>
        </div>
      ) : journey?.match?.signal_breakdown ? (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-text-primary">Signal Breakdown</h3>
          <p className="text-xs text-text-secondary">
            5-signal weighted composition (embedding: 25%, entity_overlap: 20%, token_ratio: 15%, historical: 25%, rerank: 15%)
          </p>

          <div className="space-y-2">
            {/* Embedding Cosine */}
            <div className="rounded-lg border border-bg-border bg-bg-raised p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-text-primary uppercase tracking-wide">
                  Embedding Cosine (25% weight)
                </p>
                <p className={cn('text-sm font-bold', getSignalColor(journey.match.signal_breakdown.embedding_cosine))}>
                  {journey.match.signal_breakdown.embedding_cosine.toFixed(2)}
                </p>
              </div>
              <div className="h-1.5 rounded-full bg-bg-border/30 overflow-hidden">
                <div
                  className={cn(
                    'h-full transition-all',
                    journey.match.signal_breakdown.embedding_cosine >= 0.85 ? 'bg-fit-text' :
                    journey.match.signal_breakdown.embedding_cosine >= 0.60 ? 'bg-partial-text' :
                    'bg-gap-text'
                  )}
                  style={{ width: `${Math.min(journey.match.signal_breakdown.embedding_cosine * 100, 100)}%` }}
                />
              </div>
              <p className="text-xs text-text-muted mt-1">Semantic similarity between requirement and capability</p>
            </div>

            {/* Entity Overlap */}
            <div className="rounded-lg border border-bg-border bg-bg-raised p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-text-primary uppercase tracking-wide">
                  Entity Overlap (20% weight)
                </p>
                <p className={cn('text-sm font-bold', getSignalColor(journey.match.signal_breakdown.entity_overlap))}>
                  {journey.match.signal_breakdown.entity_overlap.toFixed(2)}
                </p>
              </div>
              <div className="h-1.5 rounded-full bg-bg-border/30 overflow-hidden">
                <div
                  className={cn(
                    'h-full transition-all',
                    journey.match.signal_breakdown.entity_overlap >= 0.85 ? 'bg-fit-text' :
                    journey.match.signal_breakdown.entity_overlap >= 0.60 ? 'bg-partial-text' :
                    'bg-gap-text'
                  )}
                  style={{ width: `${Math.min(journey.match.signal_breakdown.entity_overlap * 100, 100)}%` }}
                />
              </div>
              <p className="text-xs text-text-muted mt-1">Named entities from requirement found in capability text</p>
            </div>

            {/* Token Ratio */}
            <div className="rounded-lg border border-bg-border bg-bg-raised p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-text-primary uppercase tracking-wide">
                  Token Ratio (15% weight)
                </p>
                <p className={cn('text-sm font-bold', getSignalColor(journey.match.signal_breakdown.token_ratio))}>
                  {journey.match.signal_breakdown.token_ratio.toFixed(2)}
                </p>
              </div>
              <div className="h-1.5 rounded-full bg-bg-border/30 overflow-hidden">
                <div
                  className={cn(
                    'h-full transition-all',
                    journey.match.signal_breakdown.token_ratio >= 0.85 ? 'bg-fit-text' :
                    journey.match.signal_breakdown.token_ratio >= 0.60 ? 'bg-partial-text' :
                    'bg-gap-text'
                  )}
                  style={{ width: `${Math.min(journey.match.signal_breakdown.token_ratio * 100, 100)}%` }}
                />
              </div>
              <p className="text-xs text-text-muted mt-1">String similarity via token-level matching</p>
            </div>

            {/* Historical Alignment */}
            <div className="rounded-lg border border-bg-border bg-bg-raised p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-text-primary uppercase tracking-wide">
                  Historical Alignment (25% weight)
                </p>
                <p className={cn('text-sm font-bold', getSignalColor(journey.match.signal_breakdown.historical_alignment))}>
                  {journey.match.signal_breakdown.historical_alignment.toFixed(2)}
                </p>
              </div>
              <div className="h-1.5 rounded-full bg-bg-border/30 overflow-hidden">
                <div
                  className={cn(
                    'h-full transition-all',
                    journey.match.signal_breakdown.historical_alignment >= 0.85 ? 'bg-fit-text' :
                    journey.match.signal_breakdown.historical_alignment >= 0.60 ? 'bg-partial-text' :
                    'bg-gap-text'
                  )}
                  style={{ width: `${Math.min(journey.match.signal_breakdown.historical_alignment * 100, 100)}%` }}
                />
              </div>
              <p className="text-xs text-text-muted mt-1">Prior fitments from previous waves (1.0 if exists, 0.0 if not)</p>
            </div>

            {/* Rerank Score */}
            <div className="rounded-lg border border-bg-border bg-bg-raised p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-text-primary uppercase tracking-wide">
                  Rerank Score (15% weight)
                </p>
                <p className={cn('text-sm font-bold', getSignalColor(journey.match.signal_breakdown.rerank_score))}>
                  {journey.match.signal_breakdown.rerank_score.toFixed(2)}
                </p>
              </div>
              <div className="h-1.5 rounded-full bg-bg-border/30 overflow-hidden">
                <div
                  className={cn(
                    'h-full transition-all',
                    journey.match.signal_breakdown.rerank_score >= 0.85 ? 'bg-fit-text' :
                    journey.match.signal_breakdown.rerank_score >= 0.60 ? 'bg-partial-text' :
                    'bg-gap-text'
                  )}
                  style={{ width: `${Math.min(journey.match.signal_breakdown.rerank_score * 100, 100)}%` }}
                />
              </div>
              <p className="text-xs text-text-muted mt-1">Cross-encoder reranking score from Phase 2 retrieval</p>
            </div>
          </div>
        </div>
      ) : null}

      {/* Info Banner */}
      <div className="rounded-lg border border-accent/20 bg-accent/5 p-4 flex gap-3">
        <AlertCircle className="h-4 w-4 text-accent-glow shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="text-xs font-medium text-text-primary mb-1">Phase 3 Signal Analysis</p>
          <p className="text-xs text-text-secondary leading-relaxed">
            Five weighted signals are combined to produce a composite score that determines routing. Anomalies flag scenarios where semantic similarity is high but named entities don't overlap, indicating possible false positives.
          </p>
        </div>
      </div>
    </div>
  )
}
