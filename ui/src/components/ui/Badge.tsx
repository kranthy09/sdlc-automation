import { cn } from '@/lib/utils'
import type { Classification, BatchStatus } from '@/api/types'

export type BadgeVariant = Classification | BatchStatus | 'default'

const STYLE: Record<string, string> = {
  FIT: 'bg-fit-muted text-fit-text border-fit/30',
  PARTIAL_FIT: 'bg-partial-muted text-partial-text border-partial/30',
  GAP: 'bg-gap-muted text-gap-text border-gap/30',
  queued: 'bg-bg-raised text-text-secondary border-bg-border',
  running: 'bg-accent/10 text-accent-glow border-accent/30',
  review_pending: 'bg-partial-muted text-partial-text border-partial/30',
  complete: 'bg-fit-muted text-fit-text border-fit/30',
  failed: 'bg-gap-muted text-gap-text border-gap/30',
  default: 'bg-bg-raised text-text-secondary border-bg-border',
}

const LABEL: Record<string, string> = {
  FIT: 'Fit',
  PARTIAL_FIT: 'Partial Fit',
  GAP: 'Gap',
  queued: 'Queued',
  running: 'Running',
  review_pending: 'Review Pending',
  complete: 'Complete',
  failed: 'Failed',
}

interface BadgeProps {
  variant: BadgeVariant
  label?: string
  className?: string
}

export function Badge({ variant, label, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        STYLE[variant] ?? STYLE.default,
        className,
      )}
    >
      {label ?? LABEL[variant] ?? variant}
    </span>
  )
}
