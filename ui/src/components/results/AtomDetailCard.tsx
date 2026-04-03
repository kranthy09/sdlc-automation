import { Check, AlertCircle, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { AtomJourney } from '@/api/types'
import { EvidencePanel } from './EvidencePanel'
import { SignalRadar } from './SignalRadar'
import { JourneyFlow } from './JourneyFlow'

const JOURNEY_STAGES = [
  { id: 'ingest', label: 'Ingest', icon: '📄' },
  { id: 'retrieve', label: 'Retrieve', icon: '🔍' },
  { id: 'match', label: 'Match', icon: '⚡' },
  { id: 'classify', label: 'Classify', icon: '🏷️' },
  { id: 'output', label: 'Output', icon: '✓' },
]

const ROUTE_COLOR: Record<string, string> = {
  FAST_TRACK: 'bg-fit-muted text-fit-text border-fit',
  DEEP_REASON: 'bg-partial-muted text-partial-text border-partial',
  GAP_CONFIRM: 'bg-gap-muted text-gap-text border-gap',
}

const getScoreColor = (score: number): string => {
  if (score >= 0.7) return 'text-fit-text'
  if (score >= 0.4) return 'text-partial-text'
  return 'text-gap-text'
}

const EFFORT_COLOR: Record<string, string> = {
  S: 'bg-fit-muted text-fit-text',
  M: 'bg-partial-muted text-partial-text',
  L: 'bg-gap-muted text-gap-text',
}

interface AtomDetailCardProps {
  journey: AtomJourney
  expanded?: boolean
}

export function AtomDetailCard({ journey, expanded = false }: AtomDetailCardProps) {
  const ingest = journey.ingest
  const retrieve = journey.retrieve
  const match = journey.match
  const classify = journey.classify
  const output = journey.output

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-6 space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-sm font-semibold text-text-primary mb-2">{ingest.requirement_text}</h3>
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center rounded-md bg-bg-raised px-2.5 py-0.5 text-xs font-medium text-text-secondary">
            {ingest.atom_id}
          </span>
          <span className="inline-flex items-center rounded-md bg-bg-raised px-2.5 py-0.5 text-xs font-medium text-text-secondary">
            Module: {ingest.module}
          </span>
          <span className={cn(
            'inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-medium',
            output.classification === 'FIT' ? 'bg-fit-muted text-fit-text' :
            output.classification === 'PARTIAL_FIT' ? 'bg-partial-muted text-partial-text' :
            'bg-gap-muted text-gap-text'
          )}>
            {output.classification}
          </span>
        </div>
      </div>

      {/* Journey flow visualization */}
      <JourneyFlow journey={journey} />

      {/* Signal radar */}
      {match && (
        <div>
          <p className="mb-3 text-xs font-medium text-text-muted uppercase tracking-wide">Composite Score Breakdown</p>
          <div className="rounded-lg border border-bg-border bg-bg-raised/50 p-4">
            <SignalRadar
              signals={match.signal_breakdown}
              compositeScore={match.composite_score}
            />
          </div>
        </div>
      )}

      {/* Match details */}
      {match && (
        <div>
          <p className="mb-3 text-xs font-medium text-text-muted uppercase tracking-wide">Match Details</p>
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-1">Composite Score</p>
              <p className={cn('text-lg font-bold', getScoreColor(match.composite_score))}>
                {Math.round(match.composite_score * 100)}%
              </p>
            </div>
            <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-1">Route</p>
              <p className="text-xs font-medium text-text-primary">{match.route}</p>
            </div>
            <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-1">Anomalies</p>
              <p className={cn('text-lg font-bold', match.anomaly_flags.length > 0 ? 'text-gap-text' : 'text-fit-text')}>
                {match.anomaly_flags.length}
              </p>
            </div>
          </div>
          {match.anomaly_flags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {match.anomaly_flags.map((flag) => (
                <span key={flag} className="inline-flex items-center rounded-md bg-gap-muted/20 px-2.5 py-0.5 text-xs font-medium text-gap-text border border-gap/30">
                  {flag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Classification */}
      {classify && (
        <div>
          <p className="mb-3 text-xs font-medium text-text-muted uppercase tracking-wide">Classification</p>
          <div className="space-y-3">
            <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-1">AI Decision</p>
              <div className="flex items-center gap-2">
                <span className={cn(
                  'inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-medium',
                  classify.classification === 'FIT' ? 'bg-fit-muted text-fit-text' :
                  classify.classification === 'PARTIAL_FIT' ? 'bg-partial-muted text-partial-text' :
                  'bg-gap-muted text-gap-text'
                )}>
                  {classify.classification}
                </span>
                <p className={cn('text-sm font-semibold', getScoreColor(classify.confidence))}>
                  {Math.round(classify.confidence * 100)}%
                </p>
                {classify.route_used && (
                  <span className={cn('rounded border px-2 py-1 text-xs font-medium', ROUTE_COLOR[classify.route_used] || 'bg-bg-raised text-text-secondary border-bg-border')}>
                    {classify.route_used}
                  </span>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-2">Rationale</p>
              <p className="text-xs text-text-secondary leading-relaxed">{classify.rationale}</p>
            </div>
            <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-2">D365 Capability</p>
              <p className="text-xs font-medium text-text-primary">{classify.d365_capability}</p>
              <p className="text-xs text-text-muted mt-1">{classify.d365_navigation}</p>
            </div>
          </div>
        </div>
      )}

      {/* Output details */}
      {output && (
        <div>
          <p className="mb-3 text-xs font-medium text-text-muted uppercase tracking-wide">Output</p>
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-1">Final Classification</p>
              <span className={cn(
                'inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-medium',
                output.classification === 'FIT' ? 'bg-fit-muted text-fit-text' :
                output.classification === 'PARTIAL_FIT' ? 'bg-partial-muted text-partial-text' :
                'bg-gap-muted text-gap-text'
              )}>
                {output.classification}
              </span>
            </div>
            <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-1">Confidence</p>
              <p className={cn('text-lg font-bold', getScoreColor(output.confidence))}>
                {Math.round(output.confidence * 100)}%
              </p>
            </div>
            <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-1">Dev Effort</p>
              {output.dev_effort ? (
                <span className={cn('inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-medium', EFFORT_COLOR[output.dev_effort] || 'bg-bg-raised text-text-secondary')}>
                  {output.dev_effort}
                </span>
              ) : (
                <p className="text-xs text-text-muted">—</p>
              )}
            </div>
          </div>
          {output.gap_description && (
            <div className="mt-3 rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-2">Gap Description</p>
              <p className="text-xs text-text-secondary">{output.gap_description}</p>
            </div>
          )}
          {output.classification === 'PARTIAL_FIT' && (
            <div className="mt-3 rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
              <p className="text-xs text-text-muted mb-2">Configuration Steps</p>
              {(() => {
                const steps = output.configuration_steps && output.configuration_steps.length > 0
                  ? output.configuration_steps
                  : output.config_steps
                  ? [output.config_steps]
                  : []
                return steps.length > 0 ? (
                  <ol className="space-y-1">
                    {steps.map((step, i) => (
                      <li key={i} className="text-xs text-text-secondary flex gap-2">
                        <span className="font-medium text-text-muted">{i + 1}.</span>
                        <span>{step}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-xs italic text-text-muted">
                    Configuration steps were not generated by the LLM for this PARTIAL_FIT. Review the D365 capability and refer to MS Learn documentation for configuration guidance.
                  </p>
                )
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
