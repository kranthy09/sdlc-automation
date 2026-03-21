import { useParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Skeleton } from '@/components/ui/Skeleton'

export default function ResultsPage() {
  const { batchId } = useParams<{ batchId: string }>()

  return (
    <div>
      <PageHeader
        title="Fitment Results"
        description={`Batch ${batchId ?? '—'}`}
      />
      <div className="px-6 space-y-4">
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-48 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    </div>
  )
}
