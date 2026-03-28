import { useProgressStore } from '@/stores/progressStore'
import { cn } from '@/lib/utils'

type WSStatus = 'connected' | 'connecting' | 'disconnected' | 'error'

interface ConnectionIndicatorProps {
  status?: WSStatus
  className?: string
}

const STATUS_CONFIG: Record<WSStatus, { label: string; color: string; pulse: boolean }> = {
  connected: {
    label: 'Live',
    color: 'bg-fit-text',
    pulse: false,
  },
  connecting: {
    label: 'Connecting',
    color: 'bg-partial-text',
    pulse: true,
  },
  disconnected: {
    label: 'Offline',
    color: 'bg-text-muted',
    pulse: false,
  },
  error: {
    label: 'Error',
    color: 'bg-gap-text',
    pulse: true,
  },
}

export function ConnectionIndicator({ status = 'connected', className }: ConnectionIndicatorProps) {
  const config = STATUS_CONFIG[status]

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div className={cn('h-2 w-2 rounded-full', config.color, config.pulse && 'animate-pulse')} />
      <span className="text-xs text-text-muted">{config.label}</span>
    </div>
  )
}
