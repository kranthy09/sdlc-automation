import type { Classification } from '@/api/types'

const inputCls =
  'w-full rounded-lg border border-bg-border bg-bg-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent'

interface OverrideFormProps {
  classification: Classification | null
  reason: string
  onClassification: (c: Classification) => void
  onReason: (r: string) => void
}

const OPTIONS: Array<{ value: Classification; label: string }> = [
  { value: 'FIT', label: 'Fit' },
  { value: 'PARTIAL_FIT', label: 'Partial Fit' },
  { value: 'GAP', label: 'Gap' },
]

export function OverrideForm({
  classification,
  reason,
  onClassification,
  onReason,
}: OverrideFormProps) {
  return (
    <div className="space-y-3 rounded-lg border border-partial/20 bg-partial-muted/10 p-3">
      <div>
        <label className="mb-1 block text-xs font-medium text-text-secondary">
          Override classification
        </label>
        <select
          className={inputCls}
          value={classification ?? ''}
          onChange={(e) => onClassification(e.target.value as Classification)}
        >
          <option value="" disabled>
            Select…
          </option>
          {OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-text-secondary">
          Reason <span className="text-gap-text">*</span>
        </label>
        <textarea
          className={inputCls}
          rows={2}
          placeholder="Why does the AI classification need to be changed?"
          value={reason}
          onChange={(e) => onReason(e.target.value)}
        />
      </div>
    </div>
  )
}
