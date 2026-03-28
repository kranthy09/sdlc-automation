import { ReactNode } from 'react'
import { Button } from './Button'

interface EmptyStateProps {
  icon: ReactNode
  title: string
  description: string
  action?: {
    label: string
    onClick: () => void
    variant?: 'primary' | 'secondary'
  }
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-12 text-center">
      <div className="mb-4 flex justify-center text-text-muted">
        {icon}
      </div>
      <h3 className="mb-2 text-sm font-semibold text-text-primary">{title}</h3>
      <p className="mb-6 text-xs text-text-muted max-w-sm mx-auto">{description}</p>
      {action && (
        <Button
          size="sm"
          variant={action.variant === 'secondary' ? 'ghost' : 'default'}
          onClick={action.onClick}
        >
          {action.label}
        </Button>
      )}
    </div>
  )
}
