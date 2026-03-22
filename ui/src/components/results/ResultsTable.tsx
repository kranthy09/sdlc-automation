import { ChevronUp, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ResultRow } from './ResultRow'
import { Skeleton } from '@/components/ui/Skeleton'
import type { FitmentResult, ResultsQuery } from '@/api/types'

const COLS = [
  { key: 'atom_id', label: 'Req ID', width: 'w-24' },
  { key: 'requirement_text', label: 'Requirement', width: 'flex-1' },
  { key: 'module', label: 'Module', width: 'w-24' },
  { key: 'classification', label: 'Classification', width: 'w-24' },
  { key: 'confidence', label: 'Conf.', width: 'w-14 text-right' },
] as const

interface ResultsTableProps {
  batchId: string
  results: FitmentResult[]
  total: number
  query: ResultsQuery
  loading: boolean
  onSort: (field: string) => void
  onPage: (page: number) => void
}

export function ResultsTable({ batchId, results, total, query, loading, onSort, onPage }: ResultsTableProps) {
  const page = query.page ?? 1
  const limit = query.limit ?? 25
  const totalPages = Math.ceil(total / limit)

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface overflow-hidden">
      {/* Column headers */}
      <div className="flex items-center gap-3 border-b border-bg-border bg-bg-raised px-4 py-2">
        {/* chevron spacer */}
        <div className="w-3.5 shrink-0" />
        {COLS.map((col) => (
          <button
            key={col.key}
            onClick={() => onSort(col.key)}
            className={cn(
              'flex shrink-0 items-center gap-1 text-xs font-medium text-text-muted hover:text-text-primary transition-colors',
              col.width,
            )}
          >
            {col.label}
            {query.sort === col.key &&
              (query.order === 'desc' ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronUp className="h-3 w-3" />
              ))}
          </button>
        ))}
      </div>

      {/* Body */}
      {loading ? (
        <div className="space-y-0">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="border-b border-bg-border/50 px-4 py-3">
              <Skeleton className="h-4 w-full" />
            </div>
          ))}
        </div>
      ) : results.length === 0 ? (
        <div className="flex h-32 items-center justify-center">
          <p className="text-sm text-text-muted">No results match the current filters.</p>
        </div>
      ) : (
        <div className="max-h-[600px] overflow-y-auto">
          {results.map((r) => (
            <ResultRow key={r.atom_id} result={r} batchId={batchId} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-bg-border px-4 py-2.5">
          <p className="text-xs text-text-muted">
            {(page - 1) * limit + 1}–{Math.min(page * limit, total)} of {total}
          </p>
          <div className="flex gap-2">
            <button
              disabled={page <= 1}
              onClick={() => onPage(page - 1)}
              className="rounded px-2 py-1 text-xs text-text-secondary hover:text-text-primary disabled:opacity-40 transition-colors"
            >
              Previous
            </button>
            <button
              disabled={page >= totalPages}
              onClick={() => onPage(page + 1)}
              className="rounded px-2 py-1 text-xs text-text-secondary hover:text-text-primary disabled:opacity-40 transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
