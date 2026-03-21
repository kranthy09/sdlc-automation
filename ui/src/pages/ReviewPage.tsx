import { useParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Skeleton } from '@/components/ui/Skeleton'

export default function ReviewPage() {
  const { batchId } = useParams<{ batchId: string }>()

  return (
    <div>
      <PageHeader
        title="Human Review Queue"
        description={`Batch ${batchId ?? '—'} — items flagged for review`}
      />
      <div className="px-6 space-y-4">
        <Skeleton className="h-12 rounded-xl" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-40 rounded-xl" />
        ))}
      </div>
    </div>
  )
}
