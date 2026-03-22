import { cn } from '@/lib/utils'
import type { Batch } from '@/api/types'

interface AggregateMetricsProps {
  batches: Batch[]
}

export function AggregateMetrics({ batches }: AggregateMetricsProps) {
  const completed = batches.filter((b) => b.status === 'complete')

  const totalReqs = completed.reduce(
    (sum, b) => sum + b.summary.fit + b.summary.partial_fit + b.summary.gap,
    0,
  )

  // Gap rate across all batches
  const totalGap = completed.reduce((sum, b) => sum + b.summary.gap, 0)
  const gapRate = totalReqs > 0 ? Math.round((totalGap / totalReqs) * 100) : 0

  // Fit rate
  const totalFit = completed.reduce((sum, b) => sum + b.summary.fit, 0)
  const fitRate = totalReqs > 0 ? Math.round((totalFit / totalReqs) * 100) : 0

  const metrics = [
    {
      label: 'Total requirements',
      value: totalReqs.toLocaleString(),
      sub: `${completed.length} batch${completed.length !== 1 ? 'es' : ''} complete`,
      valueClass: 'text-text-primary',
    },
    {
      label: 'Overall fit rate',
      value: `${fitRate}%`,
      sub: `${totalFit} fit`,
      valueClass: 'text-fit-text',
    },
    {
      label: 'Gap rate',
      value: `${gapRate}%`,
      sub: `${totalGap} gaps identified`,
      valueClass: gapRate > 20 ? 'text-gap-text' : 'text-partial-text',
    },
  ]

  return (
    <div className="grid grid-cols-3 gap-3">
      {metrics.map(({ label, value, sub, valueClass }) => (
        <div key={label} className="rounded-xl border border-bg-border bg-bg-surface p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-text-muted">{label}</p>
          <p className={cn('mt-1 text-2xl font-bold', valueClass)}>{value}</p>
          <p className="mt-0.5 text-xs text-text-muted">{sub}</p>
        </div>
      ))}
    </div>
  )
}
