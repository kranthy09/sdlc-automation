import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn, formatConfidence, CONFIDENCE_TIER_COLOR, confidenceTier } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import { EvidencePanel } from './EvidencePanel'
import type { FitmentResult } from '@/api/types'

interface ResultRowProps {
  result: FitmentResult
  style?: React.CSSProperties
}

export function ResultRow({ result, style }: ResultRowProps) {
  const [open, setOpen] = useState(false)

  return (
    <div style={style} className="border-b border-bg-border/50 last:border-0">
      {/* Summary row */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-bg-raised/50 transition-colors"
      >
        <ChevronRight
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-text-muted transition-transform',
            open && 'rotate-90',
          )}
        />
        <p className="w-24 shrink-0 font-mono text-xs text-text-secondary">{result.atom_id}</p>
        <p className="flex-1 truncate text-sm text-text-primary">{result.requirement_text}</p>
        <p className="w-24 shrink-0 text-xs text-text-muted">{result.module}</p>
        <div className="w-24 shrink-0">
          <Badge variant={result.classification} />
        </div>
        <p
          className={cn(
            'w-14 shrink-0 text-right text-xs font-medium',
            CONFIDENCE_TIER_COLOR[confidenceTier(result.confidence)],
          )}
        >
          {formatConfidence(result.confidence)}
        </p>
        {result.reviewer_override && (
          <span className="shrink-0 rounded-full border border-partial/30 bg-partial-muted/30 px-1.5 py-0.5 text-[10px] text-partial-text">
            Overridden
          </span>
        )}
      </button>

      {/* Evidence panel */}
      {open && (
        <div className="border-t border-bg-border/50 bg-bg-raised/30 animate-fade-in">
          <EvidencePanel
            evidence={result.evidence}
            d365Capability={result.d365_capability}
            d365Navigation={result.d365_navigation}
            rationale={result.rationale}
          />
        </div>
      )}
    </div>
  )
}
