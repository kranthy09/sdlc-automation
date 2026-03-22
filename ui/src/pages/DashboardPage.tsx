import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { BatchTable } from '@/components/dashboard/BatchTable'
import { AggregateMetrics } from '@/components/dashboard/AggregateMetrics'
import { WaveComparisonChart } from '@/components/dashboard/WaveComparisonChart'
import { Button } from '@/components/ui/Button'
import { useBatches } from '@/hooks/useBatches'

export default function DashboardPage() {
  const navigate = useNavigate()
  const { data, isLoading } = useBatches()
  const batches = data?.batches ?? []

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Batch history and aggregate fitment metrics"
        action={
          <Button size="sm" onClick={() => navigate('/upload')}>
            <Plus className="h-3.5 w-3.5" />
            New analysis
          </Button>
        }
      />

      <div className="space-y-4 px-6 pb-6">
        {/* Aggregate metrics */}
        <AggregateMetrics batches={batches} />

        {/* Wave comparison chart */}
        <WaveComparisonChart batches={batches} />

        {/* Batch history */}
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-text-muted">
            Batch history
          </p>
          <BatchTable batches={batches} loading={isLoading} />
        </div>
      </div>
    </div>
  )
}
