import { cn } from '@/lib/utils'
import type { Classification } from '@/api/types'

export type ReviewTabValue = Classification | 'ALL'

interface Tab {
  value: ReviewTabValue
  label: string
  count: number
}

interface ReviewTabsProps {
  tabs: Tab[]
  active: ReviewTabValue
  onChange: (tab: ReviewTabValue) => void
}

const TAB_ACTIVE_STYLE: Record<ReviewTabValue, string> = {
  ALL: 'border-accent text-accent-glow',
  FIT: 'border-fit text-fit-text',
  PARTIAL_FIT: 'border-partial text-partial-text',
  GAP: 'border-gap text-gap-text',
}

export function ReviewTabs({ tabs, active, onChange }: ReviewTabsProps) {
  return (
    <div className="flex gap-1 rounded-lg border border-bg-border bg-bg-raised p-1">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          onClick={() => onChange(tab.value)}
          className={cn(
            'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
            active === tab.value
              ? cn('bg-bg-surface border shadow-sm', TAB_ACTIVE_STYLE[tab.value])
              : 'text-text-muted hover:text-text-primary border border-transparent',
          )}
        >
          {tab.label}
          <span
            className={cn(
              'inline-flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold',
              active === tab.value
                ? 'bg-bg-raised text-text-primary'
                : 'bg-bg-base text-text-muted',
            )}
          >
            {tab.count}
          </span>
        </button>
      ))}
    </div>
  )
}
