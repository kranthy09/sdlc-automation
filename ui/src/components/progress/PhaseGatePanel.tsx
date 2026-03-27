import { useEffect, useState } from 'react'
import { getGateAtoms } from '@/api/dynafit'
import type {
  GateAtomsResponse,
  Phase1AtomRow,
  Phase2ContextRow,
  Phase3MatchRow,
} from '@/api/types'

interface PhaseGatePanelProps {
  batchId: string
  gate: 1 | 2 | 3 | 4
  onProceed: () => void
  proceeding: boolean
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
      return <div className="p-4 text-center text-sm text-gray-500">Loading atoms...</div>
    }

    if (error) {
      return <div className="p-4 text-center text-sm text-red-500">Error: {error}</div>
    }

    if (rows.length === 0) {
      return <div className="p-4 text-center text-sm text-gray-500">No atoms to display</div>
    }

    // Gate 1 columns
    if (gate === 1) {
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-gray-900">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left font-semibold">Requirement</th>
                <th className="px-4 py-2 text-left font-semibold">Intent</th>
                <th className="px-4 py-2 text-left font-semibold">Module</th>
                <th className="px-4 py-2 text-left font-semibold">Priority</th>
                <th className="px-4 py-2 text-right font-semibold">Completeness %</th>
              </tr>
            </thead>
            <tbody>
              {(rows as Phase1AtomRow[]).map((row) => (
                <tr key={row.atom_id} className="border-b hover:bg-gray-50">
                  <td className="px-4 py-2 max-w-xs truncate" title={row.requirement_text}>{row.requirement_text}</td>
                  <td className="px-4 py-2 truncate">{row.intent}</td>
                  <td className="px-4 py-2 truncate">{row.module}</td>
                  <td className="px-4 py-2 truncate">{row.priority}</td>
                  <td className="px-4 py-2 text-right">
                    {Math.round(row.completeness_score)}%
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
          <table className="w-full text-sm text-gray-900">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left font-semibold">Requirement</th>
                <th className="px-4 py-2 text-left font-semibold">Top D365 Capability</th>
                <th className="px-4 py-2 text-right font-semibold">Score</th>
                <th className="px-4 py-2 text-center font-semibold">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {(rows as Phase2ContextRow[]).map((row) => (
                <tr key={row.atom_id} className="border-b hover:bg-gray-50">
                  <td className="px-4 py-2 max-w-xs truncate" title={row.requirement_text}>{row.requirement_text}</td>
                  <td className="px-4 py-2 truncate">{row.top_capability}</td>
                  <td className="px-4 py-2 text-right">
                    {Math.round(row.top_capability_score * 100)}%
                  </td>
                  <td className="px-4 py-2 text-center">
                    <span
                      className={`inline-block px-2 py-1 rounded text-xs font-medium ${
                        row.retrieval_confidence === 'HIGH'
                          ? 'bg-green-100 text-green-800'
                          : row.retrieval_confidence === 'MEDIUM'
                            ? 'bg-yellow-100 text-yellow-800'
                            : 'bg-red-100 text-red-800'
                      }`}
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
          <table className="w-full text-sm text-gray-900">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left font-semibold">Requirement</th>
                <th className="px-4 py-2 text-right font-semibold">Match Score</th>
                <th className="px-4 py-2 text-left font-semibold">Route</th>
                <th className="px-4 py-2 text-left font-semibold">Anomalies</th>
              </tr>
            </thead>
            <tbody>
              {(rows as Phase3MatchRow[]).map((row) => (
                <tr key={row.atom_id} className="border-b hover:bg-gray-50">
                  <td className="px-4 py-2 max-w-xs truncate" title={row.requirement_text}>{row.requirement_text}</td>
                  <td className="px-4 py-2 text-right">
                    {Math.round(row.composite_score * 100)}%
                  </td>
                  <td className="px-4 py-2 truncate">{row.route}</td>
                  <td className="px-4 py-2 truncate">
                    {row.anomaly_flags?.length > 0 ? row.anomaly_flags.join(', ') : '—'}
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
    <div className="border rounded-lg bg-white p-6 my-6 shadow-sm">
      <div className="mb-6">
        <h3 className="text-lg font-semibold mb-2">
          {phaseNames[gate]} Gate Review
        </h3>
        <p className="text-sm text-gray-600">
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
          className="px-6 py-2 bg-blue-600 text-white rounded font-medium hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          {proceeding ? 'Processing...' : `Proceed to Phase ${nextPhaseNum}`}
        </button>
      </div>
    </div>
  )
}
