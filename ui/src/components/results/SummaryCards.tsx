import { cn } from '@/lib/utils'
import type { ResultsSummary } from '@/api/types'

interface SummaryCardsProps {
  total: number
  summary: ResultsSummary
}

const CARDS = [
  {
    key: 'total' as const,
    label: 'Total',
    valueClass: 'text-text-primary',
    borderClass: 'border-bg-border',
  },
  {
    key: 'fit' as const,
    label: 'Fit',
    valueClass: 'text-fit-text',
    borderClass: 'border-fit/20',
  },
  {
    key: 'partial_fit' as const,
    label: 'Partial Fit',
    valueClass: 'text-partial-text',
    borderClass: 'border-partial/20',
  },
  {
    key: 'gap' as const,
    label: 'Gap',
    valueClass: 'text-gap-text',
    borderClass: 'border-gap/20',
  },
]

export function SummaryCards({ total, summary }: SummaryCardsProps) {
  const values = { total, fit: summary.fit, partial_fit: summary.partial_fit, gap: summary.gap }

  return (
    <div className="grid grid-cols-4 gap-3">
      {CARDS.map(({ key, label, valueClass, borderClass }) => (
        <div
          key={key}
          className={cn(
            'rounded-xl border bg-bg-surface p-4',
            borderClass,
          )}
        >
          <p className="text-xs font-medium uppercase tracking-wide text-text-muted">{label}</p>
          <p className={cn('mt-1 text-3xl font-bold', valueClass)}>{values[key]}</p>
          {key !== 'total' && total > 0 && (
            <p className="mt-0.5 text-xs text-text-muted">
              {Math.round((values[key] / total) * 100)}%
            </p>
          )}
        </div>
      ))}
    </div>
  )
}
