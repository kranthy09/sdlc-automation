import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Scale } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { BatchTable } from '@/components/dashboard/BatchTable'
import { AggregateMetrics } from '@/components/dashboard/AggregateMetrics'
import { Button } from '@/components/ui/Button'
import { useBatches } from '@/hooks/useBatches'
import type { BatchStatus } from '@/api/types'

type SortField = 'created_at' | 'status' | 'country'
type SortOrder = 'asc' | 'desc'

export default function DashboardPage() {
  const navigate = useNavigate()
  const { data, isLoading } = useBatches()
  const batches = data?.batches ?? []
  const [statusFilter, setStatusFilter] = useState<BatchStatus | ''>('')
  const [sortField, setSortField] = useState<SortField>('created_at')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')

  const filteredBatches = useMemo(() => {
    let result = statusFilter ? batches.filter((b) => b.status === statusFilter) : batches
    result = [...result].sort((a, b) => {
      const av = a[sortField] ?? ''
      const bv = b[sortField] ?? ''
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortOrder === 'asc' ? cmp : -cmp
    })
    return result
  }, [batches, statusFilter, sortField, sortOrder])

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Batch history and aggregate fitment metrics"
        action={
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => navigate('/compare')}>
              <Scale className="h-3.5 w-3.5" />
              Compare batches
            </Button>
            <Button size="sm" onClick={() => navigate('/upload')}>
              <Plus className="h-3.5 w-3.5" />
              New analysis
            </Button>
          </div>
        }
      />

      <div className="space-y-4 px-6 pb-6">
        {/* Aggregate metrics */}
        <AggregateMetrics batches={batches} />

        {/* Batch history */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
              Batch history
            </p>
            <div className="flex items-center gap-2">
              <select
                className="rounded-lg border border-bg-border bg-bg-raised px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as BatchStatus | '')}
              >
                <option value="">All statuses</option>
                <option value="queued">Queued</option>
                <option value="running">Running</option>
                <option value="review_required">Review required</option>
                <option value="resuming">Resuming</option>
                <option value="complete">Complete</option>
                <option value="failed">Failed</option>
              </select>
              <select
                className="rounded-lg border border-bg-border bg-bg-raised px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
                value={`${sortField}:${sortOrder}`}
                onChange={(e) => {
                  const [f, o] = e.target.value.split(':') as [SortField, SortOrder]
                  setSortField(f)
                  setSortOrder(o)
                }}
              >
                <option value="created_at:desc">Newest first</option>
                <option value="created_at:asc">Oldest first</option>
                <option value="status:asc">Status A-Z</option>
                <option value="country:asc">Country A-Z</option>
              </select>
            </div>
          </div>
          <BatchTable batches={filteredBatches} loading={isLoading} />
        </div>
      </div>
    </div>
  )
}
