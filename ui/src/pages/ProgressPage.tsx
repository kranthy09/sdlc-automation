import { useNavigate, useParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { PhaseTimeline } from '@/components/progress/PhaseTimeline'
import { PhaseStatsCard } from '@/components/progress/PhaseStatsCard'
import { LiveClassTable } from '@/components/progress/LiveClassTable'
import { ReviewBanner } from '@/components/progress/ReviewBanner'
import { Button } from '@/components/ui/Button'
import { useProgress } from '@/hooks/useProgress'
import { formatDuration } from '@/lib/utils'
import { CheckCircle2, AlertCircle, Wifi } from 'lucide-react'

export default function ProgressPage() {
  const { batchId } = useParams<{ batchId: string }>()
  const navigate = useNavigate()
  const { phases, classifications, reviewRequired, complete, error, wsStatus } = useProgress(batchId!)

  const activePhase = phases.find((p) => p.status === 'active')
  const totalProcessed = phases.reduce((sum, p) => sum + p.atomsProduced, 0)

  return (
    <div>
      <PageHeader
        title="Pipeline Progress"
        description={`Batch ${batchId}`}
        action={
          complete ? (
            <Button size="sm" onClick={() => navigate(`/results/${batchId}`)}>
              View results
            </Button>
          ) : undefined
        }
      />

      <div className="space-y-4 px-6 pb-6">
        {/* Current step summary */}
        {activePhase && (
          <div className="flex items-center gap-3 rounded-xl border border-accent/20 bg-accent/5 px-5 py-3">
            <Wifi className="h-4 w-4 text-accent-glow animate-pulse-slow" />
            <div className="flex-1">
              <p className="text-sm font-medium text-text-primary">
                {activePhase.phaseName}
                {activePhase.currentStep && (
                  <span className="ml-2 text-text-secondary">— {activePhase.currentStep}</span>
                )}
              </p>
              {totalProcessed > 0 && (
                <p className="text-xs text-text-muted">{totalProcessed} atoms produced so far</p>
              )}
            </div>
            <p className="text-sm font-semibold text-accent-glow">{activePhase.progressPct}%</p>
          </div>
        )}

        {/* Phase stepper */}
        <PhaseTimeline phases={phases} />

        {/* Phase stat cards */}
        <div className="grid grid-cols-5 gap-3">
          {phases.map((p) => (
            <PhaseStatsCard key={p.phase} phase={p} />
          ))}
        </div>

        {/* Review required banner */}
        {reviewRequired && (
          <ReviewBanner
            batchId={batchId!}
            reviewItems={reviewRequired.reviewItems}
            reasons={reviewRequired.reasons}
          />
        )}

        {/* WebSocket connection error */}
        {wsStatus === 'error' && !error && (
          <div className="flex items-center gap-3 rounded-xl border border-gap/30 bg-gap-muted/20 px-5 py-4">
            <AlertCircle className="h-5 w-5 shrink-0 text-gap-text" />
            <p className="text-sm text-gap-text">Connection lost — attempting to reconnect...</p>
          </div>
        )}

        {/* Error banner */}
        {error && (
          <div className="flex items-center gap-3 rounded-xl border border-gap/30 bg-gap-muted/20 px-5 py-4">
            <AlertCircle className="h-5 w-5 shrink-0 text-gap-text" />
            <p className="text-sm text-gap-text">{error}</p>
          </div>
        )}

        {/* Complete summary */}
        {complete && (
          <div className="rounded-xl border border-fit/30 bg-fit-muted/10 px-5 py-5">
            <div className="mb-4 flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 text-fit-text" />
              <p className="text-sm font-medium text-fit-text">Pipeline complete</p>
            </div>
            <div className="grid grid-cols-4 gap-4 mb-4">
              <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3 text-center">
                <p className="text-2xl font-bold text-text-primary">{complete.total}</p>
                <p className="text-xs text-text-muted">Total</p>
              </div>
              <div className="rounded-lg border border-fit/20 bg-fit-muted/10 px-4 py-3 text-center">
                <p className="text-2xl font-bold text-fit-text">{complete.fit}</p>
                <p className="text-xs text-text-muted">
                  Fit {complete.total > 0 && `(${Math.round((complete.fit / complete.total) * 100)}%)`}
                </p>
              </div>
              <div className="rounded-lg border border-partial/20 bg-partial-muted/10 px-4 py-3 text-center">
                <p className="text-2xl font-bold text-partial-text">{complete.partial_fit}</p>
                <p className="text-xs text-text-muted">
                  Partial {complete.total > 0 && `(${Math.round((complete.partial_fit / complete.total) * 100)}%)`}
                </p>
              </div>
              <div className="rounded-lg border border-gap/20 bg-gap-muted/10 px-4 py-3 text-center">
                <p className="text-2xl font-bold text-gap-text">{complete.gap}</p>
                <p className="text-xs text-text-muted">
                  Gap {complete.total > 0 && `(${Math.round((complete.gap / complete.total) * 100)}%)`}
                </p>
              </div>
            </div>
            <Button className="w-full" onClick={() => navigate(`/results/${batchId}`)}>
              View detailed results
            </Button>
          </div>
        )}

        {/* Live classification stream */}
        {classifications.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-medium text-text-muted uppercase tracking-wide">
              Live classifications
            </p>
            <LiveClassTable rows={classifications} />
          </div>
        )}
      </div>
    </div>
  )
}
