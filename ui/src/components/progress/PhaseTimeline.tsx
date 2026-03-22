import { Check, AlertCircle, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Progress } from '@/components/ui/Progress'
import type { PhaseState } from '@/stores/progressStore'

/** Shown under the phase name when active but no step_progress has arrived yet */
const PHASE_DESCRIPTIONS: Record<number, string> = {
  1: 'Parsing document & extracting requirements...',
  2: 'Embedding & retrieving D365 capabilities...',
  3: 'Scoring signals & routing atoms...',
  4: 'Running LLM classification...',
  5: 'Validating results & checking quality...',
}

const STATUS_DOT: Record<PhaseState['status'], React.ReactNode> = {
  pending: <span className="h-5 w-5 rounded-full border-2 border-pending bg-bg-raised" />,
  active: <Loader2 className="h-5 w-5 animate-spin text-active" />,
  complete: (
    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-complete">
      <Check className="h-3 w-3 text-white" strokeWidth={3} />
    </span>
  ),
  error: (
    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-error">
      <AlertCircle className="h-3 w-3 text-white" />
    </span>
  ),
}

interface PhaseTimelineProps {
  phases: PhaseState[]
}

export function PhaseTimeline({ phases }: PhaseTimelineProps) {
  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface p-4">
      <div className="flex items-start gap-0">
        {phases.map((phase, i) => (
          <div key={phase.phase} className="flex flex-1 flex-col items-center gap-2">
            {/* Connector + dot row */}
            <div className="flex w-full items-center">
              {/* Left line */}
              <div
                className={cn(
                  'h-0.5 flex-1',
                  i === 0 ? 'invisible' : phase.status === 'complete' ? 'bg-complete' : 'bg-bg-border',
                )}
              />
              {STATUS_DOT[phase.status]}
              {/* Right line */}
              <div
                className={cn(
                  'h-0.5 flex-1',
                  i === phases.length - 1
                    ? 'invisible'
                    : phase.status === 'complete'
                      ? 'bg-complete'
                      : 'bg-bg-border',
                )}
              />
            </div>

            {/* Label */}
            <div className="w-full space-y-1 px-1 text-center">
              <p
                className={cn(
                  'text-xs font-medium',
                  phase.status === 'active'
                    ? 'text-accent-glow'
                    : phase.status === 'complete'
                      ? 'text-fit-text'
                      : phase.status === 'error'
                        ? 'text-gap-text'
                        : 'text-text-muted',
                )}
              >
                {phase.phaseName}
              </p>
              {phase.status === 'active' && (
                <Progress value={phase.progressPct} className="h-1" />
              )}
              {phase.status === 'active' && (
                <p className="truncate text-[10px] text-text-muted">
                  {phase.currentStep || PHASE_DESCRIPTIONS[phase.phase] || 'Processing...'}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
