import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import type { PIIEntityInfo } from '@/api/types'

interface RequirementPIIDetailsProps {
  entities: PIIEntityInfo[]
  piiDetected: boolean
}

export function RequirementPIIDetails({
  entities,
  piiDetected,
}: RequirementPIIDetailsProps) {
  const [expanded, setExpanded] = useState(true)

  if (!piiDetected) {
    return (
      <div className="rounded-lg border border-fit/30 bg-fit-muted/5 p-4">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-fit-text" />
          <p className="text-sm text-fit-text font-medium">No PII detected</p>
        </div>
      </div>
    )
  }

  // Group entities by type for summary
  const entityTypeCounts = entities.reduce(
    (acc, entity) => {
      acc[entity.entity_type] = (acc[entity.entity_type] || 0) + 1
      return acc
    },
    {} as Record<string, number>
  )

  const typeSummary = Object.entries(entityTypeCounts)
    .map(([type, count]) => `${count} ${type}`)
    .join(', ')

  return (
    <div className="rounded-lg border border-partial/30 bg-partial-muted/5 p-4">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 mb-3 hover:opacity-80 transition-opacity"
      >
        <div className="h-2 w-2 rounded-full bg-partial-text shrink-0" />
        <h3 className="text-sm font-semibold text-partial-text flex-1 text-left">
          PII Detected ({entities.length} entities)
        </h3>
        <ChevronDown
          className={cn('h-4 w-4 text-partial-text transition-transform shrink-0', expanded && 'rotate-180')}
        />
      </button>

      {/* Summary */}
      {expanded && (
        <div className="mb-3 text-xs text-text-secondary italic">
          {typeSummary}
        </div>
      )}

      {/* Detailed List */}
      {expanded && (
        <>
          <div className="space-y-2 mb-3">
            {entities.map((entity) => (
              <div
                key={entity.placeholder}
                className="rounded bg-bg-raised p-3 flex items-start justify-between"
              >
                <div className="flex-1">
                  <p className="text-xs font-semibold text-text-primary uppercase tracking-wide">
                    {entity.entity_type}
                  </p>
                  <p className="text-xs text-text-secondary mt-1 font-mono break-all">
                    Redacted as: {entity.placeholder}
                  </p>
                </div>
                <Badge
                  variant="default"
                  label={`${(entity.score * 100).toFixed(0)}%`}
                  className="ml-2 shrink-0"
                />
              </div>
            ))}
          </div>

          {/* Security note */}
          <div className="rounded bg-bg-raised/50 p-2.5">
            <p className="text-xs text-text-muted">
              <span className="font-semibold">ℹ️ Security Note:</span> Original sensitive values have been redacted.
              Placeholders are maintained for reference and will be restored only in the final CSV output.
            </p>
          </div>
        </>
      )}
    </div>
  )
}
