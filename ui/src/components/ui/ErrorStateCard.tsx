import { AlertCircle, RotateCcw } from 'lucide-react'
import { Button } from './Button'

interface ErrorStateCardProps {
  title?: string
  message: string
  statusCode?: number | string
  onRetry?: () => void
  retrying?: boolean
}

export function ErrorStateCard({
  title = 'Something went wrong',
  message,
  statusCode,
  onRetry,
  retrying = false,
}: ErrorStateCardProps) {
  return (
    <div className="rounded-xl border border-gap/30 bg-gap-muted/10 p-5">
      <div className="flex gap-4">
        <AlertCircle className="h-5 w-5 shrink-0 text-gap-text mt-0.5" />
        <div className="flex-1">
          <p className="mb-1 text-sm font-medium text-gap-text">{title}</p>
          <p className="text-xs text-gap-text/80 mb-3">{message}</p>
          {statusCode && (
            <p className="text-xs text-gap-text/60 mb-3">
              Error code: {statusCode}
            </p>
          )}
          {onRetry && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onRetry}
              loading={retrying}
              className="text-gap-text hover:text-gap-text hover:bg-gap-muted/20"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Retry
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
