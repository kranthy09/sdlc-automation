import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import { RequirementPIIDetails } from './RequirementPIIDetails'
import type { Phase1AtomRow } from '@/api/types'

interface RequirementDetailModalProps {
  open: boolean
  atom: Phase1AtomRow | null
  onClose: () => void
}

const getScoreColor = (score: number): string => {
  if (score >= 0.7) return 'text-fit-text'
  if (score >= 0.4) return 'text-partial-text'
  return 'text-gap-text'
}

export function RequirementDetailModal({
  open,
  atom,
  onClose,
}: RequirementDetailModalProps) {
  if (!open || !atom) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="rounded-lg border border-bg-border bg-bg-surface shadow-lg max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header with close button */}
        <div className="sticky top-0 px-6 py-4 border-b border-bg-border bg-bg-surface flex items-center justify-between">
          <h2 className="text-lg font-semibold text-text-primary">Requirement Details</h2>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors"
            aria-label="Close modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-4 space-y-6">
          {/* Requirement Text */}
          <div>
            <h3 className="text-sm font-semibold text-text-primary mb-2">Requirement</h3>
            <p className="text-sm text-text-secondary leading-relaxed whitespace-pre-wrap break-words">
              {atom.requirement_text}
            </p>
          </div>

          {/* Metadata Grid */}
          <div className="grid grid-cols-2 gap-4 py-4 border-y border-bg-border/50">
            <div>
              <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Atom ID</p>
              <p className="text-sm font-mono text-text-secondary">{atom.atom_id}</p>
            </div>
            <div>
              <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Intent</p>
              <p className="text-sm text-text-secondary">{atom.intent}</p>
            </div>
            <div>
              <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Module</p>
              <p className="text-sm text-text-secondary">{atom.module}</p>
            </div>
            <div>
              <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Priority</p>
              <p className="text-sm text-text-secondary">{atom.priority}</p>
            </div>
          </div>

          {/* Quality Scores */}
          <div>
            <h3 className="text-sm font-semibold text-text-primary mb-3">Quality Scores</h3>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-text-secondary">Completeness</span>
                <span className={cn('text-sm font-medium', getScoreColor(atom.completeness_score / 100))}>
                  {Math.round(atom.completeness_score)}%
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-text-secondary">Specificity</span>
                <span className={cn('text-sm font-medium', getScoreColor(atom.specificity_score))}>
                  {(atom.specificity_score * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </div>

          {/* PII Section */}
          <RequirementPIIDetails
            entities={atom.pii_entities || []}
            piiDetected={atom.pii_detected}
          />
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 px-6 py-4 border-t border-bg-border bg-bg-surface flex justify-end">
          <button
            onClick={onClose}
            className={cn(
              'px-4 py-2 rounded font-medium transition-colors',
              'bg-accent text-white hover:bg-accent-glow'
            )}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
