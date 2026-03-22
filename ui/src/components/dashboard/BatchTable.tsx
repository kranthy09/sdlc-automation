import { useNavigate } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { formatDate } from '@/lib/utils'
import type { Batch } from '@/api/types'

interface BatchTableProps {
  batches: Batch[]
  loading: boolean
}

export function BatchTable({ batches, loading }: BatchTableProps) {
  const navigate = useNavigate()

  if (loading) {
    return (
      <div className="space-y-0 rounded-xl border border-bg-border bg-bg-surface overflow-hidden">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="border-b border-bg-border/50 px-4 py-3">
            <Skeleton className="h-4 w-full" />
          </div>
        ))}
      </div>
    )
  }

  if (batches.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-bg-border bg-bg-surface">
        <p className="text-sm text-text-muted">No batches found.</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface overflow-hidden">
      {/* Header */}
      <div className="grid grid-cols-[minmax(0,2fr)_80px_60px_100px_100px_100px_80px_40px] items-center gap-3 border-b border-bg-border bg-bg-raised px-4 py-2">
        {['File', 'Country', 'Wave', 'Status', 'Fit/Partial/Gap', 'Created', 'Completed', ''].map(
          (h, i) => (
            <p key={i} className="text-xs font-medium text-text-muted">
              {h}
            </p>
          ),
        )}
      </div>

      {/* Rows */}
      {batches.map((batch) => (
        <div
          key={batch.batch_id}
          className="grid grid-cols-[minmax(0,2fr)_80px_60px_100px_100px_100px_80px_40px] items-center gap-3 border-b border-bg-border/50 px-4 py-3 hover:bg-bg-raised/50 last:border-0 cursor-pointer transition-colors"
          onClick={() =>
            batch.status === 'complete' || batch.status === 'review_pending'
              ? navigate(`/results/${batch.batch_id}`)
              : navigate(`/progress/${batch.batch_id}`)
          }
        >
          <p className="truncate text-sm text-text-primary">{batch.upload_filename}</p>
          <p className="text-xs text-text-secondary">{batch.country}</p>
          <p className="text-xs text-text-secondary">Wave {batch.wave}</p>
          <Badge variant={batch.status} />
          <p className="font-mono text-xs text-text-muted">
            <span className="text-fit-text">{batch.summary.fit}</span>
            {' / '}
            <span className="text-partial-text">{batch.summary.partial_fit}</span>
            {' / '}
            <span className="text-gap-text">{batch.summary.gap}</span>
          </p>
          <p className="text-xs text-text-muted">{formatDate(batch.created_at)}</p>
          <p className="text-xs text-text-muted">
            {batch.completed_at ? formatDate(batch.completed_at) : '—'}
          </p>
          <ArrowRight className="h-3.5 w-3.5 text-text-muted" />
        </div>
      ))}
    </div>
  )
}
