import { cn, formatConfidence } from '@/lib/utils'
import type { FitmentEvidence } from '@/api/types'
import { Badge } from '@/components/ui/Badge'

interface EvidencePanelProps {
  evidence: FitmentEvidence
  d365Capability: string
  d365Navigation: string
  rationale: string
}

const CONFIDENCE_COLOR = {
  HIGH: 'text-fit-text',
  MEDIUM: 'text-partial-text',
  LOW: 'text-gap-text',
}

export function EvidencePanel({
  evidence,
  d365Capability,
  d365Navigation,
  rationale,
}: EvidencePanelProps) {
  return (
    <div className="space-y-4 px-4 py-3">
      {/* Rationale */}
      <div>
        <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">
          AI Rationale
        </p>
        <p className="text-sm text-text-secondary leading-relaxed">{rationale}</p>
      </div>

      {/* D365 capability */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">
            D365 Capability
          </p>
          <p className="text-sm text-text-primary">{d365Capability}</p>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">
            Navigation
          </p>
          <p className="font-mono text-xs text-accent-glow">{d365Navigation}</p>
        </div>
      </div>

      {/* Evidence scores */}
      <div className="flex items-center gap-6">
        <div>
          <p className="text-xs text-text-muted">Capability score</p>
          <p className="text-sm font-semibold text-text-primary">
            {formatConfidence(evidence.top_capability_score)}
          </p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Retrieval confidence</p>
          <p
            className={cn(
              'text-sm font-semibold',
              CONFIDENCE_COLOR[evidence.retrieval_confidence],
            )}
          >
            {evidence.retrieval_confidence}
          </p>
        </div>
      </div>

      {/* Prior fitments */}
      {evidence.prior_fitments.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-text-muted uppercase tracking-wide">
            Prior fitments
          </p>
          <div className="flex flex-wrap gap-2">
            {evidence.prior_fitments.map((pf, i) => (
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
    </div>
  )
}
