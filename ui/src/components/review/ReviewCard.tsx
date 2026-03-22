import { useState } from 'react'
import { CheckCircle2, PenLine, Flag, ChevronDown, ChevronUp } from 'lucide-react'
import { cn, formatConfidence } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { OverrideForm } from './OverrideForm'
import type { ReviewItem, Classification, ReviewDecision } from '@/api/types'

const REASON_LABEL: Record<ReviewItem['review_reason'], string> = {
  low_confidence: 'Low confidence',
  conflict: 'Conflicting evidence',
  anomaly: 'Anomaly detected',
}

const REASON_COLOR: Record<ReviewItem['review_reason'], string> = {
  low_confidence: 'text-partial-text border-partial/30 bg-partial-muted/20',
  conflict: 'text-gap-text border-gap/30 bg-gap-muted/20',
  anomaly: 'text-accent-glow border-accent/30 bg-accent/5',
}

interface ReviewCardProps {
  item: ReviewItem
  submitting: boolean
  onDecide: (decision: ReviewDecision, overrideClass?: Classification, reason?: string) => void
}

export function ReviewCard({ item, submitting, onDecide }: ReviewCardProps) {
  const [showEvidence, setShowEvidence] = useState(false)
  const [overrideMode, setOverrideMode] = useState(false)
  const [overrideClass, setOverrideClass] = useState<Classification | null>(null)
  const [overrideReason, setOverrideReason] = useState('')

  const canSubmitOverride = overrideMode
    ? overrideClass !== null && overrideReason.trim().length > 0
    : true

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface">
      {/* Header */}
      <div className="p-5">
        {/* Review reason pill */}
        <div className="mb-3 flex items-center gap-2">
          <span
            className={cn(
              'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium',
              REASON_COLOR[item.review_reason],
            )}
          >
            {REASON_LABEL[item.review_reason]}
          </span>
          <span className="font-mono text-xs text-text-muted">{item.atom_id}</span>
        </div>

        {/* Requirement text */}
        <p className="text-base font-medium text-text-primary leading-relaxed">
          {item.requirement_text}
        </p>

        {/* AI result */}
        <div className="mt-3 flex items-center gap-3">
          <Badge variant={item.ai_classification} />
          <span className="text-sm text-text-muted">
            {formatConfidence(item.ai_confidence)} confidence
          </span>
        </div>

        {/* AI rationale */}
        <blockquote className="mt-3 border-l-2 border-bg-border pl-3 text-sm italic text-text-secondary">
          {item.ai_rationale}
        </blockquote>
      </div>

      {/* Evidence accordion */}
      <div className="border-t border-bg-border">
        <button
          onClick={() => setShowEvidence((o) => !o)}
          className="flex w-full items-center justify-between px-5 py-2.5 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          Evidence &amp; capabilities
          {showEvidence ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </button>
        {showEvidence && (
          <div className="border-t border-bg-border px-5 py-4 animate-fade-in space-y-4">
            {/* Top capabilities */}
            {item.evidence.capabilities.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-text-muted">
                  Top D365 capabilities
                </p>
                <div className="space-y-1.5">
                  {item.evidence.capabilities.slice(0, 3).map((cap) => (
                    <div key={cap.name} className="flex items-center justify-between">
                      <div>
                        <p className="text-sm text-text-primary">{cap.name}</p>
                        <p className="font-mono text-xs text-accent-glow">{cap.navigation}</p>
                      </div>
                      <span className="text-sm font-semibold text-text-secondary">
                        {formatConfidence(cap.score)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Prior fitments */}
            {item.evidence.prior_fitments.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-text-muted">
                  Prior fitments
                </p>
                <div className="flex flex-wrap gap-2">
                  {item.evidence.prior_fitments.map((pf, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-1.5 rounded-full border border-bg-border bg-bg-raised px-2.5 py-1"
                    >
                      <span className="text-xs text-text-muted">
                        Wave {pf.wave} · {pf.country}
                      </span>
                      <Badge variant={pf.classification} />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Anomaly flags */}
            {item.evidence.anomaly_flags.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-text-muted">
                  Anomaly flags
                </p>
                <ul className="space-y-1">
                  {item.evidence.anomaly_flags.map((flag, i) => (
                    <li key={i} className="text-xs text-gap-text">
                      {flag}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Override form */}
      {overrideMode && (
        <div className="border-t border-bg-border px-5 py-4">
          <OverrideForm
            classification={overrideClass}
            reason={overrideReason}
            onClassification={setOverrideClass}
            onReason={setOverrideReason}
          />
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 border-t border-bg-border px-5 py-4">
        {!overrideMode ? (
          <>
            <Button
              size="sm"
              onClick={() => onDecide('APPROVE')}
              loading={submitting}
              className="bg-fit/10 hover:bg-fit/20 text-fit-text border border-fit/30"
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              Approve
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setOverrideMode(true)}
              className="text-partial-text border-partial/30"
            >
              <PenLine className="h-3.5 w-3.5" />
              Override
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDecide('FLAG')}
              loading={submitting}
            >
              <Flag className="h-3.5 w-3.5" />
              Flag
            </Button>
          </>
        ) : (
          <>
            <Button
              size="sm"
              disabled={!canSubmitOverride}
              loading={submitting}
              onClick={() =>
                onDecide('OVERRIDE', overrideClass ?? undefined, overrideReason)
              }
              className="bg-partial/10 hover:bg-partial/20 text-partial-text border border-partial/30"
            >
              Submit override
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setOverrideMode(false)
                setOverrideClass(null)
                setOverrideReason('')
              }}
            >
              Cancel
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
