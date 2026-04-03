import { cn } from '@/lib/utils'
import type { AtomJourney } from '@/api/types'

const STAGE_COLORS: Record<string, string> = {
  ingest: 'from-blue-500 to-blue-600',
  retrieve: 'from-cyan-500 to-cyan-600',
  match: 'from-purple-500 to-purple-600',
  classify: 'from-pink-500 to-pink-600',
  output: 'from-green-500 to-green-600',
}

const STAGE_ICONS: Record<string, string> = {
  ingest: '📄',
  retrieve: '🔍',
  match: '⚡',
  classify: '🏷️',
  output: '✓',
}

const STAGE_LABELS: Record<string, string> = {
  ingest: 'Ingest',
  retrieve: 'Retrieve',
  match: 'Match',
  classify: 'Classify',
  output: 'Output',
}

interface JourneyFlowProps {
  journey: AtomJourney
}

export function JourneyFlow({ journey }: JourneyFlowProps) {
  const stages: Array<{
    id: keyof AtomJourney
    label: string
    icon: string
    color: string
    metrics?: string[]
  }> = [
    {
      id: 'ingest',
      label: STAGE_LABELS.ingest,
      icon: STAGE_ICONS.ingest,
      color: STAGE_COLORS.ingest,
      metrics: [
        `Specificity: ${Math.round(journey.ingest.specificity_score * 100)}%`,
        `Completeness: ${Math.round(journey.ingest.completeness_score * 100)}%`,
      ],
    },
    {
      id: 'retrieve',
      label: STAGE_LABELS.retrieve,
      icon: STAGE_ICONS.retrieve,
      color: STAGE_COLORS.retrieve,
      metrics: [
        `Confidence: ${journey.retrieve.retrieval_confidence}`,
        `Capabilities: ${journey.retrieve.capabilities.length}`,
      ],
    },
    {
      id: 'match',
      label: STAGE_LABELS.match,
      icon: STAGE_ICONS.match,
      color: STAGE_COLORS.match,
      metrics: [
        `Composite: ${Math.round(journey.match.composite_score * 100)}%`,
        `Route: ${journey.match.route}`,
      ],
    },
    {
      id: 'classify',
      label: STAGE_LABELS.classify,
      icon: STAGE_ICONS.classify,
      color: STAGE_COLORS.classify,
      metrics: [
        `${journey.classify.classification}`,
        `Confidence: ${Math.round(journey.classify.confidence * 100)}%`,
      ],
    },
    {
      id: 'output',
      label: STAGE_LABELS.output,
      icon: STAGE_ICONS.output,
      color: STAGE_COLORS.output,
      metrics: [
        `${journey.output.classification}`,
        journey.output.dev_effort
          ? `Effort: ${journey.output.dev_effort}`
          : journey.output.classification === 'GAP' ? 'Effort: TBD' : '',
      ],
    },
  ]

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-6">
      <p className="mb-4 text-xs font-medium text-text-muted uppercase tracking-wide">Pipeline Journey</p>

      {/* Flow diagram */}
      <div className="relative">
        {/* Connector line */}
        <div className="absolute top-8 left-0 right-0 h-1 bg-gradient-to-r from-blue-500 via-purple-500 to-green-500 rounded-full" />

        {/* Stage nodes */}
        <div className="relative flex justify-between">
          {stages.map((stage, index) => (
            <div key={stage.id} className="flex flex-col items-center flex-1">
              {/* Node circle */}
              <div
                className={cn(
                  'relative z-10 h-16 w-16 rounded-full border-4 border-bg-surface flex items-center justify-center text-2xl font-bold',
                  `bg-gradient-to-br ${stage.color}`,
                )}
              >
                {stage.icon}
              </div>

              {/* Label */}
              <p className="mt-3 text-xs font-semibold text-text-primary text-center">
                {stage.label}
              </p>

              {/* Metrics */}
              {stage.metrics && (
                <div className="mt-2 text-center space-y-0.5">
                  {stage.metrics.map((metric, i) => (
                    <p key={i} className="text-[10px] text-text-muted">
                      {metric}
                    </p>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Summary at bottom */}
      <div className="mt-6 rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
        <p className="text-xs text-text-muted mb-2">Final Output</p>
        <div className="flex items-center gap-4">
          <div>
            <p className={cn(
              'text-sm font-bold',
              journey.output.classification === 'FIT' ? 'text-fit-text' :
              journey.output.classification === 'PARTIAL_FIT' ? 'text-partial-text' :
              'text-gap-text'
            )}>
              {journey.output.classification}
            </p>
          </div>
          <div className="h-8 w-0.5 bg-bg-border" />
          <div>
            <p className="text-xs text-text-muted">Confidence</p>
            <p className="text-sm font-semibold text-text-primary">
              {Math.round(journey.output.confidence * 100)}%
            </p>
          </div>
          {journey.output.dev_effort && (
            <>
              <div className="h-8 w-0.5 bg-bg-border" />
              <div>
                <p className="text-xs text-text-muted">Dev Effort</p>
                <p className="text-sm font-semibold text-text-primary">
                  {journey.output.dev_effort}
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
