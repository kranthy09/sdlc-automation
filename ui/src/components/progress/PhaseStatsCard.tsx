import { cn, formatDuration } from '@/lib/utils'
import { Progress } from '@/components/ui/Progress'
import type { PhaseState } from '@/stores/progressStore'

const PHASE_ACTIVITY: Record<number, string> = {
  1: 'Parsing & atomising requirements',
  2: 'Embedding & capability retrieval',
  3: 'Signal scoring & routing',
  4: 'LLM classification',
  5: 'Quality validation',
}

interface PhaseStatsCardProps {
  phase: PhaseState
}

export function PhaseStatsCard({ phase }: PhaseStatsCardProps) {
  const isActive = phase.status === 'active'
  const isComplete = phase.status === 'complete'
  const isError = phase.status === 'error'

  return (
    <div
      className={cn(
        'rounded-xl border p-4 transition-all',
        isActive
          ? 'border-accent/30 bg-accent/5'
          : isComplete
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
          isActive
            ? 'text-accent-glow'
            : isComplete
              ? 'text-fit-text'
              : isError
                ? 'text-gap-text'
                : 'text-text-secondary',
        )}
      >
        {phase.phaseName}
      </p>

      {isActive && (
        <div className="space-y-2">
          <Progress value={phase.progressPct} className="h-1.5" />
          <p className="truncate text-xs text-text-muted">
            {phase.currentStep || PHASE_ACTIVITY[phase.phase] || 'Processing...'}
          </p>
          <p className="text-xs font-medium text-accent-glow">{phase.progressPct}%</p>
        </div>
      )}

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
