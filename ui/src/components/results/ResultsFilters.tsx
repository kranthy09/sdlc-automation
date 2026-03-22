import type { Classification, ResultsQuery } from '@/api/types'
import type { ResultsSummary } from '@/api/types'

interface ResultsFiltersProps {
  query: ResultsQuery
  summary: ResultsSummary
  onChange: (q: ResultsQuery) => void
}

const inputCls =
  'rounded-lg border border-bg-border bg-bg-raised px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-accent'

const CLASSIFICATIONS: Array<{ value: Classification | ''; label: string }> = [
  { value: '', label: 'All classifications' },
  { value: 'FIT', label: 'Fit' },
  { value: 'PARTIAL_FIT', label: 'Partial Fit' },
  { value: 'GAP', label: 'Gap' },
]

const SORT_OPTIONS = [
  { value: 'confidence', label: 'Confidence' },
  { value: 'atom_id', label: 'Req ID' },
  { value: 'module', label: 'Module' },
  { value: 'classification', label: 'Classification' },
]

export function ResultsFilters({ query, summary, onChange }: ResultsFiltersProps) {
  const modules = Object.keys(summary.by_module).sort()

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Classification */}
      <select
        className={inputCls}
        value={query.classification ?? ''}
        onChange={(e) =>
          onChange({
            ...query,
            classification: (e.target.value as Classification) || undefined,
            page: 1,
          })
        }
      >
        {CLASSIFICATIONS.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>

      {/* Module */}
      <select
        className={inputCls}
        value={query.module ?? ''}
        onChange={(e) =>
          onChange({ ...query, module: e.target.value || undefined, page: 1 })
        }
      >
        <option value="">All modules</option>
        {modules.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>

      {/* Sort */}
      <select
        className={inputCls}
        value={query.sort ?? 'confidence'}
        onChange={(e) => onChange({ ...query, sort: e.target.value, page: 1 })}
      >
        {SORT_OPTIONS.map((s) => (
          <option key={s.value} value={s.value}>
            Sort: {s.label}
          </option>
        ))}
      </select>

      {/* Order */}
      <select
        className={inputCls}
        value={query.order ?? 'desc'}
        onChange={(e) =>
          onChange({ ...query, order: e.target.value as 'asc' | 'desc', page: 1 })
        }
      >
        <option value="desc">Descending</option>
        <option value="asc">Ascending</option>
      </select>
    </div>
  )
}
