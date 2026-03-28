import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { AtomDetailCard } from '@/components/results/AtomDetailCard'
import { ErrorStateCard } from '@/components/ui/ErrorStateCard'
import { Button } from '@/components/ui/Button'
import { useJourney } from '@/hooks/useJourney'

export default function AtomDetailPage() {
  const { batchId, atomId } = useParams<{ batchId: string; atomId: string }>()
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useJourney(batchId!, atomId)

  if (!data?.atoms?.[0]) {
    return (
      <div>
        <PageHeader
          title="Atom Details"
          action={
            <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
              <ArrowLeft className="h-3.5 w-3.5" />
              Back
            </Button>
          }
        />
        <div className="space-y-4 px-6 pb-6">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-accent-glow" />
            </div>
          )}
          {error && (
            <ErrorStateCard
              title="Failed to load atom details"
              message={error instanceof Error ? error.message : 'Unknown error'}
              onRetry={() => refetch()}
            />
          )}
        </div>
      </div>
    )
  }

  const journey = data.atoms[0]

  return (
    <div>
      <PageHeader
        title="Atom Details"
        description={`Batch ${batchId}`}
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Button>
        }
      />

      <div className="space-y-4 px-6 pb-6">
        <AtomDetailCard journey={journey} />
      </div>
    </div>
  )
}
