import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'

const COUNTRIES = ['DE', 'FR', 'GB', 'US', 'NL', 'PL', 'ES', 'IT', 'SE', 'AU']

export interface UploadConfig {
  product: string
  country: string
  wave: number
  fitConfidenceThreshold: number
  autoApproveWithHistory: boolean
}

interface UploadConfigFormProps {
  value: UploadConfig
  onChange: (cfg: UploadConfig) => void
  disabled?: boolean
}

const inputCls =
  'w-full rounded-lg border border-bg-border bg-bg-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-1 focus:ring-offset-bg-base disabled:opacity-50'

export function UploadConfigForm({ value, onChange, disabled }: UploadConfigFormProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const set = (patch: Partial<UploadConfig>) => onChange({ ...value, ...patch })

  return (
    <div className="space-y-4">
      {/* Product */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-text-secondary">Product</label>
        <select
          value={value.product}
          onChange={(e) => set({ product: e.target.value })}
          disabled={disabled}
          className={inputCls}
        >
          <option value="d365_fo">D365 Finance &amp; Operations</option>
        </select>
      </div>

      {/* Country + Wave row */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-text-secondary">Country</label>
          <select
            value={value.country}
            onChange={(e) => set({ country: e.target.value })}
            disabled={disabled}
            className={inputCls}
          >
            <option value="">Select country…</option>
            {COUNTRIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-text-secondary">Wave</label>
          <input
            type="number"
            min={1}
            max={99}
            value={value.wave}
            onChange={(e) => set({ wave: Math.max(1, parseInt(e.target.value, 10) || 1) })}
            disabled={disabled}
            className={inputCls}
          />
        </div>
      </div>

      {/* Advanced overrides */}
      <div className="rounded-lg border border-bg-border">
        <button
          type="button"
          onClick={() => setAdvancedOpen((o) => !o)}
          className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
          disabled={disabled}
        >
          Advanced overrides
          {advancedOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
        {advancedOpen && (
          <div className="space-y-4 border-t border-bg-border px-4 py-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                Fit confidence threshold&nbsp;
                <span className="text-text-muted">(0.50 – 1.00)</span>
              </label>
              <input
                type="number"
                min={0.5}
                max={1.0}
                step={0.01}
                value={value.fitConfidenceThreshold}
                onChange={(e) =>
                  set({
                    fitConfidenceThreshold: Math.min(
                      1.0,
                      Math.max(0.5, parseFloat(e.target.value) || 0.75),
                    ),
                  })
                }
                disabled={disabled}
                className={cn(inputCls, 'w-28')}
              />
            </div>
            <label className="flex items-center gap-2.5 text-sm text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={value.autoApproveWithHistory}
                onChange={(e) => set({ autoApproveWithHistory: e.target.checked })}
                disabled={disabled}
                className="h-4 w-4 rounded border-bg-border bg-bg-raised accent-accent"
              />
              Auto-approve items with strong prior history
            </label>
          </div>
        )}
      </div>
    </div>
  )
}
