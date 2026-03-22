import { CheckCircle2, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'

interface BulkActionsProps {
  selectedCount: number
  totalCount: number
  onSelectAll: () => void
  onDeselectAll: () => void
  onBulkApprove: () => void
  loading: boolean
}

export function BulkActions({
  selectedCount,
  totalCount,
  onSelectAll,
  onDeselectAll,
  onBulkApprove,
  loading,
}: BulkActionsProps) {
  if (selectedCount === 0) return null

  return (
    <div className="flex items-center gap-3 rounded-xl border border-accent/20 bg-accent/5 px-4 py-3">
      <span className="text-sm font-medium text-text-primary">
        {selectedCount} of {totalCount} selected
      </span>
      <div className="flex items-center gap-2 ml-auto">
        {selectedCount < totalCount ? (
          <Button variant="ghost" size="sm" onClick={onSelectAll}>
            Select all
          </Button>
        ) : (
          <Button variant="ghost" size="sm" onClick={onDeselectAll}>
            <X className="h-3.5 w-3.5" />
            Deselect all
          </Button>
        )}
        <Button
          size="sm"
          onClick={onBulkApprove}
          loading={loading}
          className="bg-fit/10 hover:bg-fit/20 text-fit-text border border-fit/30"
        >
          <CheckCircle2 className="h-3.5 w-3.5" />
          Approve selected ({selectedCount})
        </Button>
      </div>
    </div>
  )
}
