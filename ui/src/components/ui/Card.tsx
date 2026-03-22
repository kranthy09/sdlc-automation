import { cn } from '@/lib/utils'

interface CardProps {
  children: React.ReactNode
  header?: React.ReactNode
  className?: string
}

export function Card({ children, header, className }: CardProps) {
  return (
    <div className={cn('rounded-xl border border-bg-border bg-bg-surface', className)}>
      {header && (
        <div className="border-b border-bg-border px-4 py-3 text-sm font-medium text-text-secondary">
          {header}
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  )
}

// Stat card variant — title + large value + optional subtitle
interface StatCardProps {
  title: string
  value: string | number
  subtitle?: string
  valueClassName?: string
  className?: string
}

export function StatCard({ title, value, subtitle, valueClassName, className }: StatCardProps) {
  return (
    <div className={cn('rounded-xl border border-bg-border bg-bg-surface p-4', className)}>
      <p className="text-xs font-medium text-text-muted uppercase tracking-wide">{title}</p>
      <p className={cn('mt-1 text-2xl font-bold text-text-primary', valueClassName)}>{value}</p>
      {subtitle && <p className="mt-0.5 text-xs text-text-muted">{subtitle}</p>}
    </div>
  )
}
