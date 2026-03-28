import { useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { Button } from './Button'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description?: string
  dangerText?: string
  confirmLabel?: string
  cancelLabel?: string
  isDangerous?: boolean
  onConfirm: () => void | Promise<void>
  onCancel: () => void
  loading?: boolean
}

export function ConfirmDialog({
  open,
  title,
  description,
  dangerText,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isDangerous = false,
  onConfirm,
  onCancel,
  loading = false,
}: ConfirmDialogProps) {
  const [isConfirming, setIsConfirming] = useState(false)

  const handleConfirm = async () => {
    setIsConfirming(true)
    try {
      await onConfirm()
    } finally {
      setIsConfirming(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="rounded-lg border border-bg-border bg-bg-surface shadow-lg max-w-sm w-full mx-4">
        {/* Header */}
        <div className="px-6 py-4 border-b border-bg-border">
          <div className="flex items-start gap-3">
            {isDangerous && (
              <AlertCircle className="h-5 w-5 text-gap-text shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
              {description && (
                <p className="text-xs text-text-muted mt-1">{description}</p>
              )}
              {dangerText && (
                <p className="text-xs text-gap-text font-medium mt-2">{dangerText}</p>
              )}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="px-6 py-4 flex gap-2 justify-end">
          <Button
            variant="ghost"
            size="sm"
            onClick={onCancel}
            disabled={isConfirming || loading}
          >
            {cancelLabel}
          </Button>
          <Button
            size="sm"
            onClick={handleConfirm}
            loading={isConfirming || loading}
            className={isDangerous ? 'bg-gap-text hover:bg-gap-text/90 text-white' : ''}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
