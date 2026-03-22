import { cn, formatDuration } from '@/lib/utils'
import type { PhaseState } from '@/stores/progressStore'

interface PhaseStatsCardProps {
  phase: PhaseState
}

export function PhaseStatsCard({ phase }: PhaseStatsCardProps) {
  const isComplete = phase.status === 'complete'
  const isError = phase.status === 'error'

  return (
    <div
      className={cn(
        'rounded-xl border p-4 transition-all',
        isComplete
          ? 'border-fit/20 bg-fit-muted/10'
          : isError
            ? 'border-gap/20 bg-gap-muted/10'
            : 'border-bg-border bg-bg-surface opacity-40',
      )}
    >
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          Phase {phase.phase}
        </p>
        {isComplete && phase.latencyMs != null && (
          <p className="text-xs text-text-muted">{formatDuration(phase.latencyMs)}</p>
        )}
      </div>
      <p
        className={cn(
          'mb-2 text-sm font-medium',
          isComplete ? 'text-fit-text' : isError ? 'text-gap-text' : 'text-text-secondary',
        )}
      >
        {phase.phaseName}
      </p>

      {isComplete && (
        <div className="space-y-1 text-xs text-text-muted">
          <div className="flex justify-between">
            <span>Produced</span>
            <span className="text-text-primary font-medium">{phase.atomsProduced}</span>
          </div>
          <div className="flex justify-between">
            <span>Validated</span>
            <span className="text-fit-text font-medium">{phase.atomsValidated}</span>
          </div>
          <div className="flex justify-between">
            <span>Flagged</span>
            <span className="text-partial-text font-medium">{phase.atomsFlagged}</span>
          </div>
        </div>
      )}
      {isError && (
        <p className="text-xs text-gap-text">Phase failed</p>
      )}
    </div>
  )
}
