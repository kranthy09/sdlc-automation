import { Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface KBSearchBarProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

export function KBSearchBar({ value, onChange, placeholder = 'Search documents...' }: KBSearchBarProps) {
  return (
    <div className="relative">
      <div className={cn(
        'flex items-center gap-3 rounded-lg border border-bg-border bg-bg-surface px-4 py-2.5',
        'focus-within:border-accent/50 focus-within:shadow-lg focus-within:shadow-accent/5 transition-all',
      )}>
        <Search className="h-4 w-4 shrink-0 text-text-muted" />

        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cn(
            'flex-1 bg-transparent text-sm text-text-primary placeholder-text-muted',
            'focus:outline-none',
          )}
          aria-label="Search documents"
        />

        {value && (
          <button
            onClick={() => onChange('')}
            className={cn(
              'rounded p-1 transition-colors',
              'hover:bg-bg-raised text-text-muted hover:text-text-primary',
              'focus:outline-none focus:ring-2 focus:ring-accent',
            )}
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  )
}
