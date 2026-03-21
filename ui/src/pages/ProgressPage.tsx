import { useParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Skeleton } from '@/components/ui/Skeleton'

export default function ProgressPage() {
  const { batchId } = useParams<{ batchId: string }>()

  return (
    <div>
      <PageHeader
        title="Pipeline Progress"
        description={`Batch ${batchId ?? '—'}`}
      />
      <div className="px-6 space-y-4">
        <Skeleton className="h-16 rounded-xl" />
        <div className="grid grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-64 rounded-xl" />
      </div>
    </div>
  )
}
