import { useState } from 'react'
import { CheckCircle2, PenLine, Flag, ChevronDown, ChevronUp, Wrench, Code2 } from 'lucide-react'
import { cn, formatConfidence, confidenceTier, CONFIDENCE_TIER_COLOR } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { OverrideForm } from './OverrideForm'
import type { ReviewItem, Classification, ReviewDecision } from '@/api/types'

const REASON_LABEL: Record<ReviewItem['review_reason'], string> = {
  low_confidence: 'Low confidence',
  anomaly: 'Anomaly detected',
  pii_detected: 'PII detected in response',
  gap_review: 'GAP — requires sign-off',
  partial_fit_no_config: 'PARTIAL_FIT — config steps missing',
}

const REASON_COLOR: Record<ReviewItem['review_reason'], string> = {
  low_confidence: 'text-partial-text border-partial/30 bg-partial-muted/20',
  anomaly: 'text-accent-glow border-accent/30 bg-accent/5',
  pii_detected: 'text-gap-text border-gap/40 bg-gap-muted/30',
  gap_review: 'text-gap-text border-gap/30 bg-gap-muted/20',
  partial_fit_no_config: 'text-partial-text border-partial/40 bg-partial-muted/30',
}

const DEV_EFFORT_LABEL: Record<string, string> = {
  S: 'Small',
  M: 'Medium',
  L: 'Large',
}

const DEV_EFFORT_COLOR: Record<string, string> = {
  S: 'bg-fit-muted text-fit-text border-fit/30',
  M: 'bg-partial-muted text-partial-text border-partial/30',
  L: 'bg-gap-muted text-gap-text border-gap/30',
}

interface ReviewCardProps {
  item: ReviewItem
  submitting: boolean
  selected?: boolean
  onToggleSelect?: () => void
  onDecide: (decision: ReviewDecision, overrideClass?: Classification, reason?: string) => void
}

export function ReviewCard({ item, submitting, selected, onToggleSelect, onDecide }: ReviewCardProps) {
  const [showEvidence, setShowEvidence] = useState(false)
  const [overrideMode, setOverrideMode] = useState(false)
  const [overrideClass, setOverrideClass] = useState<Classification | null>(null)
  const [overrideReason, setOverrideReason] = useState('')

  const canSubmitOverride = overrideMode
    ? overrideClass !== null && overrideReason.trim().length > 0
    : true

  const tier = confidenceTier(item.ai_confidence)

  return (
    <div
      className={cn(
        'rounded-xl border bg-bg-surface transition-colors',
        selected ? 'border-accent/50 ring-1 ring-accent/20' : 'border-bg-border',
      )}
    >
      {/* Header row: checkbox + module + classification + confidence */}
      <div className="p-5">
        <div className="mb-3 flex items-center gap-2 flex-wrap">
          {onToggleSelect && (
            <input
              type="checkbox"
              checked={selected ?? false}
              onChange={onToggleSelect}
              className="h-4 w-4 rounded border-bg-border text-accent focus:ring-accent"
            />
          )}
          {/* Module tag */}
          {item.module && (
            <span className="inline-flex items-center rounded-md border border-bg-border bg-bg-raised px-2 py-0.5 text-xs font-medium text-text-secondary">
              {item.module}
            </span>
          )}
          {/* Review reason pill */}
          <span
            className={cn(
              'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium',
              REASON_COLOR[item.review_reason],
            )}
          >
            {REASON_LABEL[item.review_reason]}
          </span>
          <span className="font-mono text-xs text-text-muted">{item.atom_id}</span>
          {/* Classification badge + confidence — push right */}
          <div className="ml-auto flex items-center gap-2">
            <Badge variant={item.ai_classification} />
            <span className={cn('text-sm font-semibold', CONFIDENCE_TIER_COLOR[tier])}>
              {formatConfidence(item.ai_confidence)}
            </span>
          </div>
        </div>

        {/* Requirement text */}
        <p className="text-base font-medium text-text-primary leading-relaxed">
          {item.requirement_text}
        </p>

        {/* AI rationale */}
        <blockquote className="mt-3 border-l-2 border-bg-border pl-3 text-sm italic text-text-secondary">
          {item.ai_rationale}
        </blockquote>

        {/* PARTIAL_FIT: Configuration steps — always render the block so missing data is explicit */}
        {item.ai_classification === 'PARTIAL_FIT' && (
          <div className="mt-4 rounded-lg border border-partial/20 bg-partial-muted/10 p-3">
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
                  Review the <strong>D365 capability</strong> name and <strong>rationale</strong> above. Refer to MS Learn documentation or the D365 functional specification for configuration guidance. Consider overriding if this item should be FIT or GAP.
                </p>
              </div>
            )}
          </div>
        )}

        {/* GAP: Dev effort + gap type + gap description */}
        {item.ai_classification === 'GAP' && (item.dev_effort || item.gap_type || item.gap_description) && (
          <div className="mt-4 rounded-lg border border-gap/20 bg-gap-muted/10 p-3">
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
            {(item.evidence?.capabilities?.length ?? 0) > 0 && (
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
            {(item.evidence?.prior_fitments?.length ?? 0) > 0 && (
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

            {/* MS Learn References */}
            {(item.evidence?.ms_learn_refs?.length ?? 0) > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-text-muted">
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

            {/* Anomaly flags */}
            {(item.evidence?.anomaly_flags?.length ?? 0) > 0 && (
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

            {/* GAP: show gap details + why this was classified as gap */}
            {item.ai_classification === 'GAP' && (
              <div className="rounded-lg border border-gap/20 bg-gap-muted/10 p-3 space-y-3">
                <div className="flex items-center gap-1.5 text-xs font-medium text-gap-text">
                  <Code2 className="h-3.5 w-3.5" />
                  Gap Analysis
                </div>
                {(item.evidence?.capabilities?.length ?? 0) > 0 ? (
                  <p className="text-xs text-text-muted">
                    Phase 3 retrieved <strong>{item.evidence.capabilities.length}</strong> candidate
                    {item.evidence.capabilities.length !== 1 ? 's' : ''} (top score:{' '}
                    <strong>{Math.round(item.evidence.capabilities[0].score * 100)}%</strong>). The
                    LLM evaluated these and classified this requirement as a GAP — D365 does not
                    natively cover it without custom X++ development. See the rationale above for the
                    specific reasoning.
                  </p>
                ) : (
                  <p className="text-xs text-text-muted">
                    Phase 3 found no matching capabilities in the D365 knowledge base. The LLM
                    confirmed this is a gap requiring custom X++ development or a third-party solution.
                  </p>
                )}
                {(item.dev_effort || item.gap_type) && (
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
                )}
                {item.gap_description && (
                  <p className="text-sm text-text-secondary leading-relaxed">{item.gap_description}</p>
                )}
                {!item.dev_effort && !item.gap_type && !item.gap_description && (
                  <div className="space-y-2">
                    <p className="text-xs text-text-muted italic">
                      The LLM classified this as a GAP but did not provide detailed development effort estimates, gap categorization, or description of the missing capability.
                    </p>
                    {item.caveats && (
                      <div className="rounded-md bg-bg-raised/50 p-2 border border-bg-border">
                        <p className="text-xs text-text-muted mb-1 font-medium">LLM Notes:</p>
                        <p className="text-xs text-text-secondary">{item.caveats}</p>
                      </div>
                    )}
                    <p className="text-xs text-text-muted">
                      Review the rationale above and the Phase 3 candidates to determine effort and gap type. Consider overriding if you believe this is a partial fit or fit.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Empty state for non-GAP items with no evidence */}
            {item.ai_classification !== 'GAP' &&
              (item.evidence?.capabilities?.length ?? 0) === 0 &&
              (item.evidence?.prior_fitments?.length ?? 0) === 0 &&
              (item.evidence?.anomaly_flags?.length ?? 0) === 0 && (
              <p className="text-xs text-text-muted italic">
                No retrieval evidence was found for this requirement. The LLM classified it as{' '}
                <strong>{item.ai_classification}</strong> with {Math.round(item.ai_confidence * 100)}%
                confidence. Review reason: <strong>{REASON_LABEL[item.review_reason]}</strong>. See
                the rationale above for the LLM's reasoning.
              </p>
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
      <div className="flex flex-col md:flex-row md:items-center gap-2 border-t border-bg-border px-5 py-4">
        {!overrideMode ? (
          <>
            <Button
              size="sm"
              onClick={() => onDecide('APPROVE')}
              loading={submitting}
              className="md:w-auto w-full bg-fit/10 hover:bg-fit/20 text-fit-text border border-fit/30"
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              Approve
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setOverrideMode(true)}
              className="md:w-auto w-full text-partial-text border-partial/30"
            >
              <PenLine className="h-3.5 w-3.5" />
              Override
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDecide('FLAG')}
              loading={submitting}
              className="md:w-auto w-full"
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
              className="md:w-auto w-full bg-partial/10 hover:bg-partial/20 text-partial-text border border-partial/30"
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
              className="md:w-auto w-full"
            >
              Cancel
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
