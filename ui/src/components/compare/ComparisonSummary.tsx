import { TrendingUp, TrendingDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ResultsResponse } from '@/api/types'

interface ComparisonSummaryProps {
  batch1: ResultsResponse
  batch2: ResultsResponse
}

interface DiffMetric {
  label: string
  batch1: number
  batch2: number
  diff: number
  isPercentage?: boolean
}

export function ComparisonSummary({ batch1, batch2 }: ComparisonSummaryProps) {
  const metrics: DiffMetric[] = [
    {
      label: 'Fit',
      batch1: batch1.summary.fit,
      batch2: batch2.summary.fit,
      diff: batch2.summary.fit - batch1.summary.fit,
    },
    {
      label: 'Partial Fit',
      batch1: batch1.summary.partial_fit,
      batch2: batch2.summary.partial_fit,
      diff: batch2.summary.partial_fit - batch1.summary.partial_fit,
    },
    {
      label: 'Gap',
      batch1: batch1.summary.gap,
      batch2: batch2.summary.gap,
      diff: batch2.summary.gap - batch1.summary.gap,
    },
    {
      label: 'Total Items',
      batch1: batch1.total,
      batch2: batch2.total,
      diff: batch2.total - batch1.total,
    },
  ]

  // Calculate average confidence
  const avgConf1 = batch1.results.length > 0
    ? batch1.results.reduce((sum, r) => sum + r.confidence, 0) / batch1.results.length
    : 0
  const avgConf2 = batch2.results.length > 0
    ? batch2.results.reduce((sum, r) => sum + r.confidence, 0) / batch2.results.length
    : 0

  const confidenceMetric: DiffMetric = {
    label: 'Avg Confidence',
    batch1: Math.round(avgConf1 * 100),
    batch2: Math.round(avgConf2 * 100),
    diff: Math.round((avgConf2 - avgConf1) * 100),
    isPercentage: true,
  }

  return (
    <div className="grid grid-cols-5 gap-3">
      {[...metrics, confidenceMetric].map((metric) => (
        <div
          key={metric.label}
          className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3"
        >
          <p className="text-xs text-text-muted mb-2">{metric.label}</p>
          <div className="space-y-1 mb-2">
            <p className="text-xs text-text-secondary">
              Batch 1: <span className="font-semibold text-text-primary">{metric.batch1}{metric.isPercentage ? '%' : ''}</span>
            </p>
            <p className="text-xs text-text-secondary">
              Batch 2: <span className="font-semibold text-text-primary">{metric.batch2}{metric.isPercentage ? '%' : ''}</span>
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            {metric.diff !== 0 && (
              <>
                {metric.diff > 0 ? (
                  <TrendingUp className="h-3.5 w-3.5 text-fit-text" />
                ) : (
                  <TrendingDown className="h-3.5 w-3.5 text-gap-text" />
                )}
                <span className={cn(
                  'text-xs font-semibold',
                  metric.diff > 0 ? 'text-fit-text' : 'text-gap-text'
                )}>
                  {metric.diff > 0 ? '+' : ''}{metric.diff}{metric.isPercentage ? '%' : ''}
                </span>
              </>
            )}
            {metric.diff === 0 && (
              <span className="text-xs text-text-muted">No change</span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
