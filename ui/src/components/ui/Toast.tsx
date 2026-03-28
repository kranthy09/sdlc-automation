import * as RadixToast from '@radix-ui/react-toast'
import { X, CheckCircle2, AlertCircle, Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUIStore, type NotificationType } from '@/stores/uiStore'

const ICON: Record<NotificationType, React.ComponentType<{ className?: string }>> = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
}

const STYLE: Record<NotificationType, string> = {
  success: 'border-fit text-fit-text',
  error: 'border-gap text-gap-text',
  info: 'border-accent text-accent-glow',
}

export function ToastRegion() {
  const { notifications, dismissNotification } = useUIStore()

  return (
    <RadixToast.Provider swipeDirection="right">
      {notifications.map((n) => {
        const Icon = ICON[n.type]
        return (
          <RadixToast.Root
            key={n.id}
            open
            onOpenChange={(open) => !open && dismissNotification(n.id)}
            duration={5_000}
            role="alert"
            aria-live="assertive"
            className={cn(
              'flex items-start gap-3 rounded-lg border bg-bg-surface px-4 py-3 shadow-lg',
              'data-[state=open]:animate-slide-up data-[state=closed]:animate-fade-in',
              STYLE[n.type],
            )}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" />
            <RadixToast.Description className="flex-1 text-sm text-text-primary">
              {n.message}
            </RadixToast.Description>
            <RadixToast.Close asChild>
              <button className="text-text-muted hover:text-text-primary transition-colors">
                <X className="h-3.5 w-3.5" />
              </button>
            </RadixToast.Close>
          </RadixToast.Root>
        )
      })}
      <RadixToast.Viewport className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2" />
    </RadixToast.Provider>
  )
}
