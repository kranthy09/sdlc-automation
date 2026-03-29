import { useState } from 'react'
import { ChevronDown, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getGateAtoms } from '@/api/dynafit'
import type { Phase1AtomRow, PIIEntityInfo } from '@/api/types'

interface PIIStatusExpandableProps {
  atomsFlagged: number
  batchId: string
  onAtomClick?: (atom: Phase1AtomRow) => void
}

export function PIIStatusExpandable({
  atomsFlagged,
  batchId,
  onAtomClick,
}: PIIStatusExpandableProps) {
  const [expanded, setExpanded] = useState(false)
  const [atoms, setAtoms] = useState<Phase1AtomRow[]>([])
  const [loading, setLoading] = useState(false)

  const handleExpand = async () => {
    if (expanded) {
      setExpanded(false)
      return
    }

    if (atoms.length === 0 && !loading) {
      setLoading(true)
      try {
        // Fetch atoms from gate 1
        const resp = await getGateAtoms(batchId, 1)
        const piiAtoms = (resp.rows || []).filter((atom: Phase1AtomRow) => atom.pii_detected)
        setAtoms(piiAtoms)
      } catch (err) {
        console.error('Error fetching PII atoms:', err)
      } finally {
        setLoading(false)
      }
    }

    setExpanded(true)
  }

  // Calculate entity type summary from all atoms
  const entityTypeCounts: Record<string, number> = {}
  atoms.forEach((atom) => {
    (atom.pii_entities || []).forEach((entity) => {
      entityTypeCounts[entity.entity_type] = (entityTypeCounts[entity.entity_type] || 0) + 1
    })
  })

  const entitySummary = Object.entries(entityTypeCounts)
    .sort(([, a], [, b]) => b - a)
    .map(([type, count]) => `${count} ${type}`)
    .join(', ')

  return (
    <div>
      {/* Summary/Header */}
      <button
        onClick={handleExpand}
        className="flex items-center gap-2 text-xs leading-relaxed hover:opacity-80 transition-opacity w-full text-left"
        title={expanded ? 'Collapse PII details' : 'Expand to see PII-flagged atoms'}
      >
        <ChevronDown
          className={cn('h-4 w-4 text-partial-text shrink-0 transition-transform', expanded && 'rotate-180')}
        />
        <span className="text-partial-text font-medium">
          {atomsFlagged} item{atomsFlagged !== 1 ? 's' : ''} flagged for PII
        </span>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="mt-3 space-y-2">
          {loading && (
            <div className="text-xs text-text-muted italic py-2">Loading atoms...</div>
          )}

          {!loading && atoms.length === 0 && (
            <div className="text-xs text-text-muted italic py-2">No atoms with PII found</div>
          )}

          {!loading && atoms.length > 0 && (
            <>
              {/* Entity type summary */}
              <div className="text-xs text-text-muted bg-bg-raised/50 rounded px-2.5 py-1.5">
                <span className="font-semibold">Types detected:</span> {entitySummary}
              </div>

              {/* Atom list */}
              <div className="max-h-48 overflow-y-auto space-y-1">
                {atoms.map((atom) => (
                  <button
                    key={atom.atom_id}
                    onClick={() => onAtomClick?.(atom)}
                    className="w-full flex items-start gap-2 rounded bg-bg-raised/40 hover:bg-bg-raised/70 px-2.5 py-1.5 transition-colors text-left group"
                  >
                    <AlertCircle className="h-3.5 w-3.5 text-partial-text shrink-0 mt-0.5 group-hover:text-accent transition-colors" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-mono text-text-secondary group-hover:text-accent truncate transition-colors">
                        {atom.atom_id}
                      </p>
                      <p className="text-xs text-text-muted mt-0.5 truncate">
                        {atom.pii_entities && atom.pii_entities.length > 0
                          ? `${atom.pii_entities.length} entit${atom.pii_entities.length === 1 ? 'y' : 'ies'}: ${atom.pii_entities.map((e) => e.entity_type).join(', ')}`
                          : 'No PII data'}
                      </p>
                    </div>
                  </button>
                ))}
              </div>

              {/* Footer */}
              <p className="text-xs text-text-muted italic pt-1">
                Click an atom to view full details
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
