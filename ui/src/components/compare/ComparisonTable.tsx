import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import type { FitmentResult } from '@/api/types'

interface ComparisonTableProps {
  results1: FitmentResult[]
  results2: FitmentResult[]
}

export function ComparisonTable({ results1, results2 }: ComparisonTableProps) {
  const [expandedAtomId, setExpandedAtomId] = useState<string | null>(null)

  // Create a map of atom_id to result for quick lookup
  const map2 = new Map(results2.map((r) => [r.atom_id, r]))

  // Find atoms that changed classification
  const changedAtoms = results1
    .filter((r1) => {
      const r2 = map2.get(r1.atom_id)
      return r2 && r2.classification !== r1.classification
    })
    .sort((a, b) => (map2.get(b.atom_id)?.confidence ?? 0) - (map2.get(a.atom_id)?.confidence ?? 0))

  if (changedAtoms.length === 0) {
    return (
      <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-6 text-center">
        <p className="text-sm text-text-muted">
          No classification changes between batches. Results are identical.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface overflow-hidden">
      {/* Header */}
      <div className="grid grid-cols-[40px_minmax(0,2fr)_100px_100px_100px_80px] items-center gap-3 border-b border-bg-border bg-bg-raised px-4 py-2">
        {['', 'Requirement', 'Batch 1', 'Batch 2', 'Confidence', ''].map((h, i) => (
          <p key={i} className="text-xs font-medium text-text-muted">
            {h}
          </p>
        ))}
      </div>

      {/* Rows */}
      {changedAtoms.map((r1) => {
        const r2 = map2.get(r1.atom_id)!
        const isExpanded = expandedAtomId === r1.atom_id

        return (
          <div key={r1.atom_id}>
            {/* Main row */}
            <div
              className={cn(
                'grid grid-cols-[40px_minmax(0,2fr)_100px_100px_100px_80px] items-center gap-3 border-b border-bg-border/50 px-4 py-3 hover:bg-bg-raised/50 cursor-pointer transition-colors',
                isExpanded && 'border-b-0 bg-bg-raised/30'
              )}
              onClick={() => setExpandedAtomId(isExpanded ? null : r1.atom_id)}
            >
              <button className="flex items-center justify-center rounded hover:bg-bg-border transition-colors p-1">
                <ChevronRight
                  className={cn(
                    'h-4 w-4 text-text-muted transition-transform',
                    isExpanded && 'rotate-90'
                  )}
                />
              </button>
              <p className="truncate text-sm text-text-primary">{r1.requirement_text}</p>
              <Badge variant={r1.classification} />
              <Badge variant={r2.classification} />
              <p className="text-xs text-text-muted text-right">
                {Math.round(r2.confidence * 100)}%
              </p>
              <div className="text-right">
                {r1.classification !== r2.classification && (
                  <span className="inline-flex items-center rounded-md bg-partial-muted px-2 py-0.5 text-xs font-medium text-partial-text border border-partial/30">
                    Changed
                  </span>
                )}
              </div>
            </div>

            {/* Expanded detail row */}
            {isExpanded && (
              <div className="border-b border-bg-border/50 px-4 py-4 bg-bg-raised/20">
                <div className="grid grid-cols-2 gap-4 max-w-4xl">
                  {/* Batch 1 details */}
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-text-muted uppercase">Batch 1</p>
                    <div className="rounded-lg border border-bg-border bg-bg-raised px-3 py-2 space-y-2">
                      <div>
                        <p className="text-xs text-text-muted">D365 Capability</p>
                        <p className="text-xs text-text-secondary">{r1.d365_capability}</p>
                      </div>
                      {r1.dev_effort && (
                        <div>
                          <p className="text-xs text-text-muted">Dev Effort</p>
                          <p className="text-xs text-text-secondary">{r1.dev_effort}</p>
                        </div>
                      )}
                      <div>
                        <p className="text-xs text-text-muted">Confidence</p>
                        <p className="text-xs text-text-secondary">{Math.round(r1.confidence * 100)}%</p>
                      </div>
                    </div>
                  </div>

                  {/* Batch 2 details */}
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-text-muted uppercase">Batch 2</p>
                    <div className="rounded-lg border border-bg-border bg-bg-raised px-3 py-2 space-y-2">
                      <div>
                        <p className="text-xs text-text-muted">D365 Capability</p>
                        <p className="text-xs text-text-secondary">{r2.d365_capability}</p>
                      </div>
                      {r2.dev_effort && (
                        <div>
                          <p className="text-xs text-text-muted">Dev Effort</p>
                          <p className="text-xs text-text-secondary">{r2.dev_effort}</p>
                        </div>
                      )}
                      <div>
                        <p className="text-xs text-text-muted">Confidence</p>
                        <p className="text-xs text-text-secondary">{Math.round(r2.confidence * 100)}%</p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
