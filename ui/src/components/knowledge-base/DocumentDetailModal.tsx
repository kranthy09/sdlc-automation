import { X, ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/Button'
import type { DocumentItem } from '@/api/types'

interface DocumentDetailModalProps {
  document: DocumentItem | null
  onClose: () => void
}

export function DocumentDetailModal({ document, onClose }: DocumentDetailModalProps) {
  if (!document) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Modal Panel */}
      <div className="fixed inset-4 z-50 overflow-hidden rounded-xl border border-bg-border bg-bg-surface shadow-xl flex flex-col md:inset-[5%] lg:inset-[10%]">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-bg-border px-6 py-4">
          <div className="flex-1">
            <p className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
              {document.module}
            </p>
            <h2 className="text-lg font-semibold text-text-primary">{document.title}</h2>
            <p className="text-sm text-text-secondary mt-1">{document.feature}</p>
          </div>

          <button
            onClick={onClose}
            className={cn(
              'rounded-lg p-1.5 transition-colors',
              'hover:bg-bg-raised text-text-secondary hover:text-text-primary',
              'focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-bg-surface',
            )}
            aria-label="Close modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <p className="whitespace-pre-wrap text-sm text-text-secondary leading-relaxed">
              {document.text}
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-bg-border bg-bg-raised px-6 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted">ID:</span>
            <span className="font-mono text-xs text-text-secondary">{document.id}</span>
          </div>

          {document.url && (
            <a
              href={document.url}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium',
                'bg-accent text-white hover:bg-accent/90 transition-colors',
                'focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-bg-raised',
              )}
            >
              View on MS Learn
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}

          <Button onClick={onClose} variant="ghost" size="sm">
            Close
          </Button>
        </div>
      </div>
    </>
  )
}
