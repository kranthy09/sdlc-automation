import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import { getGateAtoms } from '@/api/dynafit'
import type {
  GateAtomsResponse,
  Phase1AtomRow,
  Phase2ContextRow,
  Phase3MatchRow,
  ProgressClassificationItem,
} from '@/api/types'

interface PhaseGatePanelProps {
  batchId: string
  gate: 1 | 2 | 3 | 4
  onProceed: () => void
  proceeding: boolean
}

const ROUTE_COLOR: Record<string, string> = {
  FAST_TRACK: 'bg-fit-muted text-fit-text border-fit',
  DEEP_REASON: 'bg-partial-muted text-partial-text border-partial',
  GAP_CONFIRM: 'bg-gap-muted text-gap-text border-gap',
}

const getScoreColor = (score: number): string => {
  if (score >= 0.7) return 'text-fit-text'
  if (score >= 0.4) return 'text-partial-text'
  return 'text-gap-text'
}

export function PhaseGatePanel({
  batchId,
  gate,
  onProceed,
  proceeding,
}: PhaseGatePanelProps) {
  const [rows, setRows] = useState<unknown[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    ;(async () => {
      try {
        setLoading(true)
        setError(null)
        const resp = await getGateAtoms(batchId, gate)
        setRows(resp.rows)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load gate atoms')
      } finally {
        setLoading(false)
      }
    })()
  }, [batchId, gate])

  const phaseNames: Record<1 | 2 | 3 | 4, string> = {
    1: 'Ingestion',
    2: 'RAG',
    3: 'Matching',
    4: 'Classification',
  }

  const renderTable = () => {
    if (gate === 4) {
      // Gate 4: no table, just header + button (classifications already visible above)
      return null
    }

    if (loading) {
      return <div className="p-4 text-center text-sm text-text-muted">Loading atoms...</div>
    }

    if (error) {
      return <div className="p-4 text-center text-sm text-gap-text">Error: {error}</div>
    }

    if (rows.length === 0) {
      return <div className="p-4 text-center text-sm text-text-muted">No atoms to display</div>
    }

    // Gate 1 columns
    if (gate === 1) {
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-text-primary">
            <thead className="bg-bg-raised border-b border-bg-border">
              <tr>
                <th className="px-4 py-2 text-left font-semibold text-text-primary">Requirement</th>
                <th className="px-4 py-2 text-left font-semibold text-text-primary">Intent</th>
                <th className="px-4 py-2 text-left font-semibold text-text-primary">Module</th>
                <th className="px-4 py-2 text-left font-semibold text-text-primary">Priority</th>
                <th className="px-4 py-2 text-right font-semibold text-text-primary">Completeness</th>
                <th className="px-4 py-2 text-right font-semibold text-text-primary">Specificity</th>
              </tr>
            </thead>
            <tbody>
              {(rows as Phase1AtomRow[]).map((row) => (
                <tr key={row.atom_id} className="border-b border-bg-border/50 hover:bg-bg-raised/50 transition-colors">
                  <td className="px-4 py-2 max-w-xs truncate text-text-secondary" title={row.requirement_text}>{row.requirement_text}</td>
                  <td className="px-4 py-2 truncate text-text-secondary">{row.intent}</td>
                  <td className="px-4 py-2 truncate text-text-secondary">{row.module}</td>
                  <td className="px-4 py-2 truncate text-text-secondary">{row.priority}</td>
                  <td className={cn('px-4 py-2 text-right font-medium', getScoreColor(row.completeness_score / 100))}>
                    {Math.round(row.completeness_score)}%
                  </td>
                  <td className={cn('px-4 py-2 text-right font-medium', getScoreColor(row.specificity_score))}>
                    {(row.specificity_score * 100).toFixed(0)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }

    // Gate 2 columns
    if (gate === 2) {
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-text-primary">
            <thead className="bg-bg-raised border-b border-bg-border">
              <tr>
                <th className="px-4 py-2 text-left font-semibold text-text-primary">Requirement</th>
                <th className="px-4 py-2 text-left font-semibold text-text-primary">Top D365 Capability</th>
                <th className="px-4 py-2 text-right font-semibold text-text-primary">Score</th>
                <th className="px-4 py-2 text-center font-semibold text-text-primary">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {(rows as Phase2ContextRow[]).map((row) => (
                <tr key={row.atom_id} className="border-b border-bg-border/50 hover:bg-bg-raised/50 transition-colors">
                  <td className="px-4 py-2 max-w-xs truncate text-text-secondary" title={row.requirement_text}>{row.requirement_text}</td>
                  <td className="px-4 py-2 truncate text-text-secondary">{row.top_capability}</td>
                  <td className="px-4 py-2 text-right text-text-secondary">
                    {Math.round(row.top_capability_score * 100)}%
                  </td>
                  <td className="px-4 py-2 text-center">
                    <span
                      className={cn(
                        'inline-block px-2 py-1 rounded text-xs font-medium border',
                        row.retrieval_confidence === 'HIGH'
                          ? 'bg-fit-muted text-fit-text border-fit'
                          : row.retrieval_confidence === 'MEDIUM'
                            ? 'bg-partial-muted text-partial-text border-partial'
                            : 'bg-gap-muted text-gap-text border-gap'
                      )}
                    >
                      {row.retrieval_confidence}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }

    // Gate 3 columns
    if (gate === 3) {
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-text-primary">
            <thead className="bg-bg-raised border-b border-bg-border">
              <tr>
                <th className="px-4 py-2 text-left font-semibold text-text-primary">Requirement</th>
                <th className="px-4 py-2 text-right font-semibold text-text-primary">Match Score</th>
                <th className="px-4 py-2 text-left font-semibold text-text-primary">Route</th>
                <th className="px-4 py-2 text-left font-semibold text-text-primary">Anomalies</th>
              </tr>
            </thead>
            <tbody>
              {(rows as Phase3MatchRow[]).map((row) => (
                <tr key={row.atom_id} className="border-b border-bg-border/50 hover:bg-bg-raised/50 transition-colors">
                  <td className="px-4 py-2 max-w-xs truncate text-text-secondary" title={row.requirement_text}>{row.requirement_text}</td>
                  <td className={cn('px-4 py-2 text-right font-medium', getScoreColor(row.composite_score))}>
                    {Math.round(row.composite_score * 100)}%
                  </td>
                  <td className="px-4 py-2 truncate">
                    <span className={cn('rounded border px-2 py-1 text-xs font-medium inline-block', ROUTE_COLOR[row.route] || 'bg-bg-raised border-bg-border text-text-secondary')}>
                      {row.route}
                    </span>
                  </td>
                  <td className="px-4 py-2 truncate">
                    {row.anomaly_flags?.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {row.anomaly_flags.map((f) => (
                          <span key={f} className="rounded border border-partial bg-partial-muted/30 px-1.5 py-0.5 text-xs text-partial-text">
                            {f}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-text-muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }

    return null
  }

  const nextPhaseNum = gate + 1
  const nextPhaseName = ['', 'RAG', 'Matching', 'Classification', 'Validation'][nextPhaseNum]

  return (
    <div className="border border-bg-border rounded-lg bg-bg-surface p-6 my-6">
      <div className="mb-6">
        <h3 className="text-lg font-semibold mb-2 text-text-primary">
          {phaseNames[gate]} Gate Review
        </h3>
        <p className="text-sm text-text-secondary">
          {loading
            ? `Review and approve to proceed to ${nextPhaseName}.`
            : `${rows.length} atoms produced. Review and approve to proceed to ${nextPhaseName}.`}
        </p>
      </div>

      {renderTable()}

      <div className="mt-6 flex justify-end">
        <button
          onClick={onProceed}
          disabled={proceeding}
          className={cn(
            'px-6 py-2 rounded font-medium transition-colors',
            proceeding
              ? 'bg-bg-border text-text-muted cursor-not-allowed'
              : 'bg-accent text-white hover:bg-accent-glow'
          )}
        >
          {proceeding ? 'Processing...' : `Proceed to Phase ${nextPhaseNum}`}
        </button>
      </div>
    </div>
  )
}
