import { X, CheckCircle2, AlertCircle, Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/uiStore'
import type { NotificationType } from '@/stores/uiStore'

const ICON_MAP: Record<NotificationType, React.ReactNode> = {
  success: <CheckCircle2 className="h-4 w-4" />,
  error: <AlertCircle className="h-4 w-4" />,
  info: <Info className="h-4 w-4" />,
}

const COLOR_MAP: Record<NotificationType, string> = {
  success: 'text-fit-text',
  error: 'text-gap-text',
  info: 'text-accent-glow',
}

const BG_COLOR_MAP: Record<NotificationType, string> = {
  success: 'bg-fit-muted/20 border-fit/30',
  error: 'bg-gap-muted/20 border-gap/30',
  info: 'bg-accent/10 border-accent/30',
}

interface NotificationHistoryProps {
  open: boolean
  onClose: () => void
}

export function NotificationHistory({ open, onClose }: NotificationHistoryProps) {
  const { notificationHistory } = useUIStore()

  if (!open) return null

  return (
    <div className="fixed right-0 top-0 h-screen w-96 max-w-full z-40 bg-bg-surface border-l border-bg-border shadow-lg flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-bg-border flex items-center justify-between">
        <p className="text-sm font-semibold text-text-primary">Notification History</p>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-bg-raised transition-colors"
        >
          <X className="h-4 w-4 text-text-muted" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {notificationHistory.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-text-muted text-xs">
            No notifications yet
          </div>
        ) : (
          <div className="divide-y divide-bg-border/50">
            {notificationHistory.map((notification) => (
              <div
                key={notification.id}
                className={cn(
                  'px-4 py-3 border-l-2 flex items-start gap-3 hover:bg-bg-raised/50 transition-colors',
                  BG_COLOR_MAP[notification.type],
                )}
              >
                <div className={cn('mt-0.5 shrink-0', COLOR_MAP[notification.type])}>
                  {ICON_MAP[notification.type]}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-text-secondary line-clamp-3">
                    {notification.message}
                  </p>
                  {notification.timestamp && (
                    <p className="text-[10px] text-text-muted mt-1">
                      {new Date(notification.timestamp).toLocaleTimeString()}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
