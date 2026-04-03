import { useState } from 'react'
import { useArtifacts } from '@/hooks/useArtifacts'
import { getArtifactUrl } from '@/api/dynafit'
import { ModalityBadge } from './ModalityBadge'
import { Skeleton } from '@/components/ui/Skeleton'
import { Table2, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ArtifactGalleryProps {
  batchId: string
}

/**
 * Gallery display of extracted artifacts (TABLE_IMAGE, TABLE_DATAFRAME, FIGURE_IMAGE).
 * Shows thumbnail tiles grouped by type, with lightbox on click.
 * Silently returns null if no artifacts available (old pipeline path).
 */
export function ArtifactGallery({ batchId }: ArtifactGalleryProps) {
  const { data, isLoading } = useArtifacts(batchId)
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div>
        <p className="mb-3 text-xs text-text-muted">Loading artifacts...</p>
        <div className="grid grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="aspect-video rounded-lg" />
          ))}
        </div>
      </div>
    )
  }

  if (!data?.artifacts || data.artifacts.length === 0) {
    return (
      <p className="text-xs text-text-muted italic">
        No images or tables were extracted from this document.
      </p>
    )
  }

  const groupedByType = data.artifacts.reduce(
    (acc, artifact) => {
      const type = artifact.artifact_type
      if (!acc[type]) acc[type] = []
      acc[type].push(artifact)
      return acc
    },
    {} as Record<string, typeof data.artifacts>,
  )

  const counts = Object.entries(groupedByType)
    .map(([type, artifacts]) => {
      const displayType = type === 'TABLE_IMAGE' ? 'table images' : type === 'FIGURE_IMAGE' ? 'figures' : 'dataframes'
      return `${artifacts.length} ${displayType}`
    })
    .join(' · ')

  return (
    <div>
      <p className="mb-3 text-xs text-text-muted">{counts} extracted</p>
      <div className="space-y-6">
        {Object.entries(groupedByType).map(([type, artifacts]) => (
          <div key={type}>
            <h4 className="mb-2 text-xs font-medium text-text-secondary uppercase tracking-wide">
              <ModalityBadge modality={type === 'TABLE_IMAGE' ? 'TABLE' : 'IMAGE'} size="sm" />
            </h4>
            <div className="grid grid-cols-3 gap-3">
              {artifacts.map((artifact) => (
                <div key={artifact.artifact_id}>
                  {type === 'TABLE_DATAFRAME' ? (
                    // Parquet file — show icon tile
                    <div className="flex flex-col items-center justify-center rounded-lg border border-bg-border bg-bg-raised p-4 aspect-video cursor-default">
                      <Table2 className="h-6 w-6 text-text-muted mb-2" />
                      <span className="text-xs text-text-muted">Parquet</span>
                    </div>
                  ) : (
                    // Image tile
                    <button
                      type="button"
                      className={cn(
                        'relative w-full aspect-video rounded-lg border border-bg-border overflow-hidden',
                        'hover:border-accent transition-all hover:shadow-lg cursor-pointer',
                        'bg-bg-raised',
                      )}
                      onClick={() => setSelectedArtifact(artifact.artifact_id)}
                      title={`Click to view ${artifact.filename}`}
                    >
                      <img
                        src={getArtifactUrl(batchId, artifact.artifact_id)}
                        alt={artifact.filename}
                        className="w-full h-full object-contain"
                        onError={(e) => {
                          e.currentTarget.style.display = 'none'
                        }}
                      />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Lightbox modal */}
      {selectedArtifact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80">
          <div className="relative max-w-4xl max-h-screen overflow-auto">
            <button
              type="button"
              onClick={() => setSelectedArtifact(null)}
              className="absolute top-4 right-4 p-2 rounded-lg bg-bg-surface hover:bg-bg-raised transition-colors"
            >
              <X className="h-5 w-5 text-text-primary" />
            </button>
            <img
              src={getArtifactUrl(batchId, selectedArtifact)}
              alt="Full-size artifact"
              className="max-h-screen object-contain"
            />
            <div className="mt-4 px-4 pb-4">
              <p className="text-sm text-text-muted text-center">
                {data.artifacts.find((a) => a.artifact_id === selectedArtifact)?.filename}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
