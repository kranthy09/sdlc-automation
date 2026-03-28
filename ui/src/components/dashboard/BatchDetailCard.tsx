import { Download, ExternalLink, Copy, Check } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/Button'
import { formatDate } from '@/lib/utils'
import type { Batch } from '@/api/types'

interface BatchDetailCardProps {
  batch: Batch
  onNavigate?: (path: string) => void
}

export function BatchDetailCard({ batch, onNavigate }: BatchDetailCardProps) {
  const [copiedField, setCopiedField] = useState<string | null>(null)

  const copyToClipboard = (text: string, field: string) => {
    navigator.clipboard.writeText(text)
    setCopiedField(field)
    setTimeout(() => setCopiedField(null), 2000)
  }

  const renderValue = (value: string | number | null | undefined) => {
    if (value === null || value === undefined) return '—'
    return value
  }

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-5 space-y-4">
      {/* Summary row */}
      <div className="grid grid-cols-4 gap-3">
        <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
          <p className="text-xs text-text-muted mb-1">Product</p>
          <p className="text-sm font-medium text-text-primary">{batch.product}</p>
        </div>
        <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
          <p className="text-xs text-text-muted mb-1">Country</p>
          <p className="text-sm font-medium text-text-primary">{batch.country}</p>
        </div>
        <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
          <p className="text-xs text-text-muted mb-1">Wave</p>
          <p className="text-sm font-medium text-text-primary">{batch.wave}</p>
        </div>
        <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
          <p className="text-xs text-text-muted mb-1">Total Items</p>
          <p className="text-sm font-medium text-text-primary">
            {batch.summary.fit + batch.summary.partial_fit + batch.summary.gap}
          </p>
        </div>
      </div>

      {/* Batch ID and timestamps */}
      <div className="space-y-3">
        <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
          <p className="text-xs text-text-muted mb-2">Batch ID</p>
          <div className="flex items-center gap-2">
            <p className="font-mono text-xs text-text-secondary flex-1 break-all">{batch.batch_id}</p>
            <button
              onClick={() => copyToClipboard(batch.batch_id, 'batch_id')}
              className="p-1 rounded hover:bg-bg-border transition-colors"
              title="Copy to clipboard"
            >
              {copiedField === 'batch_id' ? (
                <Check className="h-4 w-4 text-fit-text" />
              ) : (
                <Copy className="h-4 w-4 text-text-muted" />
              )}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs text-text-muted mb-1">Created</p>
            <p className="text-xs text-text-secondary">{formatDate(batch.created_at)}</p>
            <p className="text-xs text-text-muted mt-1">{new Date(batch.created_at).toLocaleTimeString()}</p>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs text-text-muted mb-1">Completed</p>
            {batch.completed_at ? (
              <>
                <p className="text-xs text-text-secondary">{formatDate(batch.completed_at)}</p>
                <p className="text-xs text-text-muted mt-1">{new Date(batch.completed_at).toLocaleTimeString()}</p>
              </>
            ) : (
              <p className="text-xs text-text-muted">—</p>
            )}
          </div>
        </div>
      </div>

      {/* Fitment summary */}
      <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
        <p className="text-xs text-text-muted mb-3">Fitment Breakdown</p>
        <div className="grid grid-cols-3 gap-3">
          <div className="text-center">
            <p className="text-lg font-bold text-fit-text">{batch.summary.fit}</p>
            <p className="text-xs text-text-muted">Fit</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold text-partial-text">{batch.summary.partial_fit}</p>
            <p className="text-xs text-text-muted">Partial</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold text-gap-text">{batch.summary.gap}</p>
            <p className="text-xs text-text-muted">Gap</p>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        {(batch.status === 'complete' || batch.status === 'review_required') && (
          <>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onNavigate?.(`/results/${batch.batch_id}`)}
              className="flex-1"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              View Results
            </Button>
            <Button size="sm" variant="ghost" className="flex-1">
              <Download className="h-3.5 w-3.5" />
              Download Report
            </Button>
          </>
        )}
        {batch.status !== 'complete' && batch.status !== 'review_required' && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onNavigate?.(`/progress/${batch.batch_id}`)}
            className="flex-1"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            View Progress
          </Button>
        )}
      </div>
    </div>
  )
}
