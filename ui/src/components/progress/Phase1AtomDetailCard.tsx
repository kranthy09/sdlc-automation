import { AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import { RequirementPIIDetails } from './RequirementPIIDetails'
import type { Phase1AtomRow } from '@/api/types'

interface Phase1AtomDetailCardProps {
  atom: Phase1AtomRow | null
  expanded?: boolean
}

const getScoreColor = (score: number): string => {
  if (score >= 70) return 'text-fit-text'
  if (score >= 40) return 'text-partial-text'
  return 'text-gap-text'
}

const getScoreColorFloat = (score: number): string => {
  if (score >= 0.7) return 'text-fit-text'
  if (score >= 0.4) return 'text-partial-text'
  return 'text-gap-text'
}

const getPriorityColor = (priority: string): string => {
  switch (priority?.toLowerCase()) {
    case 'must':
      return 'bg-gap-muted text-gap-text border-gap'
    case 'should':
      return 'bg-partial-muted text-partial-text border-partial'
    case 'could':
    case 'nice':
      return 'bg-fit-muted text-fit-text border-fit'
    default:
      return 'bg-bg-raised text-text-secondary border-bg-border'
  }
}

export function Phase1AtomDetailCard({
  atom,
  expanded = true,
}: Phase1AtomDetailCardProps) {
  if (!atom) {
    return (
      <div className="rounded-lg border border-bg-border bg-bg-surface/50 p-6">
        <p className="text-sm text-text-muted">No atom selected</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-bg-border bg-bg-surface/50 p-6 space-y-6">
      {/* Requirement Text */}
      <div>
        <h3 className="text-sm font-semibold text-text-primary mb-3">Requirement</h3>
        <p className="text-sm text-text-secondary leading-relaxed whitespace-pre-wrap break-words">
          {atom.requirement_text}
        </p>
      </div>

      {/* Metadata Grid */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-text-primary">Metadata</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Atom ID</p>
            <p className="text-sm font-mono text-text-secondary">{atom.atom_id}</p>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Intent</p>
            <p className="text-sm text-text-secondary">{atom.intent}</p>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Module</p>
            <p className="text-sm text-text-secondary">{atom.module}</p>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">Priority</p>
            <div className="flex items-center">
              <span className={cn(
                'inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-medium border',
                getPriorityColor(atom.priority)
              )}>
                {atom.priority}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Quality Scores */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-text-primary">Quality Assessment</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs text-text-muted mb-2">Completeness Score</p>
            <div className="flex items-baseline gap-2">
              <p className={cn('text-2xl font-bold', getScoreColor(atom.completeness_score))}>
                {Math.round(atom.completeness_score)}
              </p>
              <p className="text-xs text-text-muted">/ 100</p>
            </div>
            {/* Score bar */}
            <div className="mt-2 h-1.5 rounded-full bg-bg-border/30 overflow-hidden">
              <div
                className={cn(
                  'h-full transition-all',
                  atom.completeness_score >= 70 ? 'bg-fit-text' :
                  atom.completeness_score >= 40 ? 'bg-partial-text' :
                  'bg-gap-text'
                )}
                style={{ width: `${Math.min(atom.completeness_score, 100)}%` }}
              />
            </div>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <p className="text-xs text-text-muted mb-2">Specificity Score</p>
            <div className="flex items-baseline gap-2">
              <p className={cn('text-2xl font-bold', getScoreColorFloat(atom.specificity_score))}>
                {Math.round(atom.specificity_score * 100)}
              </p>
              <p className="text-xs text-text-muted">%</p>
            </div>
            {/* Score bar */}
            <div className="mt-2 h-1.5 rounded-full bg-bg-border/30 overflow-hidden">
              <div
                className={cn(
                  'h-full transition-all',
                  atom.specificity_score >= 0.7 ? 'bg-fit-text' :
                  atom.specificity_score >= 0.4 ? 'bg-partial-text' :
                  'bg-gap-text'
                )}
                style={{ width: `${Math.min(atom.specificity_score * 100, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* PII Details */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-text-primary">Security & Privacy</h3>
        <RequirementPIIDetails
          entities={atom.pii_entities || []}
          piiDetected={atom.pii_detected}
        />
      </div>

      {/* Info Banner */}
      <div className="rounded-lg border border-accent/20 bg-accent/5 p-4 flex gap-3">
        <AlertCircle className="h-4 w-4 text-accent-glow shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="text-xs font-medium text-text-primary mb-1">Atom Processing</p>
          <p className="text-xs text-text-secondary leading-relaxed">
            This atom has been extracted, validated, and scored during Phase 1 ingestion. PII has been redacted using placeholders for security. Original sensitive data is never exposed in the UI.
          </p>
        </div>
      </div>
    </div>
  )
}
