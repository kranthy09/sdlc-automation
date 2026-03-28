import { useBatches } from '@/hooks/useBatches'
import { Skeleton } from '@/components/ui/Skeleton'

interface ComparisonSelectorProps {
  label: string
  value?: string
  onChange: (batchId: string) => void
  excludeId?: string
}

export function ComparisonSelector({
  label,
  value,
  onChange,
  excludeId,
}: ComparisonSelectorProps) {
  const { data, isLoading } = useBatches()
  const batches = data?.batches ?? []

  // Filter to completed batches only, and exclude the other comparison batch
  const completedBatches = batches.filter(
    (b) => (b.status === 'complete' || b.status === 'review_required') && b.batch_id !== excludeId
  )

  if (isLoading) {
    return <Skeleton className="h-10 rounded-lg" />
  }

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-text-muted uppercase tracking-wide">
        {label}
      </label>
      <select
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-bg-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
      >
        <option value="">Select a batch...</option>
        {completedBatches.map((batch) => (
          <option key={batch.batch_id} value={batch.batch_id}>
            {batch.upload_filename} ({batch.country} • Wave {batch.wave})
          </option>
        ))}
      </select>
      {completedBatches.length === 0 && (
        <p className="text-xs text-text-muted">
          No completed batches available for comparison.
        </p>
      )}
    </div>
  )
}
