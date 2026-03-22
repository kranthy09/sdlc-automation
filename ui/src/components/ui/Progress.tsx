import { cn } from '@/lib/utils'

interface ProgressProps {
  value: number // 0-100
  color?: 'accent' | 'fit' | 'partial' | 'gap'
  className?: string
}

const COLOR = {
  accent: 'bg-accent',
  fit: 'bg-fit',
  partial: 'bg-partial',
  gap: 'bg-gap',
}

export function Progress({ value, color = 'accent', className }: ProgressProps) {
  const pct = Math.min(100, Math.max(0, value))
  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-bg-raised', className)}>
      <div
        className={cn('h-full rounded-full transition-all duration-300', COLOR[color])}
        style={{ width: `${pct}%` }}
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      />
    </div>
  )
}
