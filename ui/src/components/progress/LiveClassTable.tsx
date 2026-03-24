import { useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { formatConfidence } from '@/lib/utils'
import { ChevronRight } from 'lucide-react'
import type { LiveClassificationRow } from '@/stores/progressStore'

const COL_WIDTHS = ['w-24', 'flex-1', 'w-28', 'w-16', 'w-28', 'w-6']
const HEADERS = ['Req ID', 'Requirement', 'Classification', 'Conf.', 'Module', '']

interface LiveClassTableProps {
  rows: LiveClassificationRow[]
}

export function LiveClassTable({ rows }: LiveClassTableProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (rows.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-bg-border bg-bg-surface">
        <p className="text-sm text-text-muted">Classifications will appear here as they stream in…</p>
      </div>
    )
  }

  const toggle = (atomId: string) =>
    setExpandedId((prev) => (prev === atomId ? null : atomId))

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-bg-border bg-bg-raised px-4 py-2">
        {HEADERS.map((h, i) => (
          <p key={h} className={`${COL_WIDTHS[i]} shrink-0 text-xs font-medium text-text-muted`}>
            {h}
          </p>
        ))}
      </div>

      {/* Scrollable body */}
      <div className="overflow-y-auto" style={{ maxHeight: 400 }}>
        {rows.map((row) => {
          const isOpen = expandedId === row.atomId
          const hasJourney = !!row.journey
          return (
            <div key={row.atomId} className="animate-fade-in">
              {/* Row */}
              <div
                className={`flex items-start gap-2 border-b border-bg-border/50 px-4 py-2 ${
                  hasJourney ? 'cursor-pointer hover:bg-bg-raised/50' : ''
                }`}
                onClick={() => hasJourney && toggle(row.atomId)}
              >
                <p className="w-24 shrink-0 font-mono text-xs text-text-secondary">{row.atomId}</p>
                <p className="flex-1 text-xs text-text-primary leading-relaxed">{row.requirementText}</p>
                <div className="w-28 shrink-0">
                  <Badge variant={row.classification} />
                </div>
                <p className="w-16 shrink-0 text-xs text-text-secondary">
                  {formatConfidence(row.confidence)}
                </p>
                <p className="w-28 shrink-0 truncate text-xs text-text-muted">{row.module}</p>
                <div className="w-6 shrink-0 flex justify-center">
                  {hasJourney && (
                    <ChevronRight
                      className={`h-3.5 w-3.5 text-text-muted transition-transform ${isOpen ? 'rotate-90' : ''}`}
                    />
                  )}
                </div>
              </div>

              {/* Expanded evidence panel */}
              {isOpen && row.journey && (
                <JourneyEvidence journey={row.journey} rationale={row.rationale} />
              )}
            </div>
          )
        })}
      </div>

      <div className="border-t border-bg-border px-4 py-2">
        <p className="text-xs text-text-muted">{rows.length} classified</p>
      </div>
    </div>
  )
}

// ─── Inline evidence panel ───────────────────────────────────────────────────

interface JourneyEvidenceProps {
  journey: NonNullable<LiveClassificationRow['journey']>
  rationale: string
}

function JourneyEvidence({ journey, rationale }: JourneyEvidenceProps) {
  return (
    <div className="border-b border-bg-border/50 bg-bg-raised/30 px-6 py-3 space-y-3 text-xs">
      {/* Rationale */}
      {rationale && (
        <div>
          <p className="font-medium text-text-secondary mb-1">Rationale</p>
          <p className="text-text-primary leading-relaxed">{rationale}</p>
        </div>
      )}

      {/* D365 Capability match */}
      {journey.classify && journey.classify.d365_capability && (
        <div>
          <p className="font-medium text-text-secondary mb-1">D365 Capability</p>
          <p className="text-text-primary">
            {journey.classify.d365_capability}
            {journey.classify.d365_navigation && (
              <span className="ml-2 text-text-muted">({journey.classify.d365_navigation})</span>
            )}
          </p>
        </div>
      )}

      {/* Retrieved capabilities */}
      {journey.retrieve?.capabilities && journey.retrieve.capabilities.length > 0 && (
        <div>
          <p className="font-medium text-text-secondary mb-1">Top Capabilities</p>
          <div className="space-y-1">
            {journey.retrieve.capabilities.slice(0, 3).map((cap) => (
              <div key={cap.name} className="flex items-center gap-2">
                <span className="font-mono text-accent-glow">{cap.score.toFixed(2)}</span>
                <span className="text-text-primary">{cap.name}</span>
                {cap.navigation && (
                  <span className="text-text-muted">— {cap.navigation}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Signal breakdown */}
      {journey.match?.signal_breakdown && Object.keys(journey.match.signal_breakdown).length > 0 && (
        <div>
          <p className="font-medium text-text-secondary mb-1">Signal Breakdown</p>
          <div className="flex flex-wrap gap-3">
            {Object.entries(journey.match.signal_breakdown).map(([key, value]) => (
              <div key={key} className="flex items-center gap-1">
                <span className="text-text-muted">{key.replace(/_/g, ' ')}:</span>
                <span className="font-mono text-text-primary">{(value as number).toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Route + composite score */}
      <div className="flex gap-4 text-text-muted">
        {journey.match?.route && <span>Route: <span className="text-text-primary">{journey.match.route}</span></span>}
        {journey.match?.composite_score != null && (
          <span>Composite: <span className="font-mono text-text-primary">{journey.match.composite_score.toFixed(2)}</span></span>
        )}
        {journey.classify?.llm_calls_used != null && (
          <span>LLM calls: <span className="text-text-primary">{journey.classify.llm_calls_used}</span></span>
        )}
      </div>
    </div>
  )
}
