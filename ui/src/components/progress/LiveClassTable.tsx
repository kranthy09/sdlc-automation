import { useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Badge } from '@/components/ui/Badge'
import { formatConfidence } from '@/lib/utils'
import type { LiveClassificationRow } from '@/stores/progressStore'

const COL_WIDTHS = ['w-24', 'flex-1', 'w-28', 'w-16', 'w-28']
const HEADERS = ['Req ID', 'Requirement', 'Classification', 'Conf.', 'Module']

interface LiveClassTableProps {
  rows: LiveClassificationRow[]
}

export function LiveClassTable({ rows }: LiveClassTableProps) {
  const parentRef = useRef<HTMLDivElement>(null)

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 40,
    overscan: 8,
  })

  if (rows.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-bg-border bg-bg-surface">
        <p className="text-sm text-text-muted">Classifications will appear here as they stream in…</p>
      </div>
    )
  }

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

      {/* Virtualized body */}
      <div
        ref={parentRef}
        className="overflow-y-auto"
        style={{ height: Math.min(rows.length * 40, 320) }}
      >
        <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
          {rowVirtualizer.getVirtualItems().map((vRow) => {
            const row = rows[vRow.index]
            return (
              <div
                key={row.atomId}
                style={{
                  position: 'absolute',
                  top: vRow.start,
                  left: 0,
                  right: 0,
                  height: vRow.size,
                }}
                className="flex items-center gap-2 border-b border-bg-border/50 px-4 animate-fade-in"
              >
                <p className="w-24 shrink-0 font-mono text-xs text-text-secondary">{row.atomId}</p>
                <p className="flex-1 truncate text-xs text-text-primary">{row.requirementText}</p>
                <div className="w-28 shrink-0">
                  <Badge variant={row.classification} />
                </div>
                <p className="w-16 shrink-0 text-xs text-text-secondary">
                  {formatConfidence(row.confidence)}
                </p>
                <p className="w-28 shrink-0 truncate text-xs text-text-muted">{row.module}</p>
              </div>
            )
          })}
        </div>
      </div>

      <div className="border-t border-bg-border px-4 py-2">
        <p className="text-xs text-text-muted">{rows.length} classified</p>
      </div>
    </div>
  )
}
