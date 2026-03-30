import { ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DocumentItem } from '@/api/types'

interface DocumentCardProps {
  document: DocumentItem
  onClick: () => void
}

export function DocumentCard({ document, onClick }: DocumentCardProps) {
  return (
    <button
      onClick={onClick}
      aria-label={`View ${document.title}`}
      title={`View details for: ${document.title}`}
      className={cn(
        'group relative flex h-full flex-col gap-3 rounded-xl border border-bg-border bg-bg-surface p-4',
        'transition-all hover:border-accent/50 hover:shadow-lg hover:shadow-accent/5',
        'text-left focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-bg-base',
      )}
    >
      {/* Module Badge */}
      <div className="flex items-start gap-2">
        <span className="inline-flex rounded border border-bg-border bg-bg-raised px-2 py-1 text-xs font-medium text-text-secondary">
          {document.module}
        </span>
      </div>

      {/* Title */}
      <div className="flex-1">
        <h3 className="text-sm font-semibold text-text-primary line-clamp-2 group-hover:text-accent transition-colors">
          {document.title}
        </h3>
      </div>

      {/* Feature */}
      <p className="text-xs text-text-muted line-clamp-1">{document.feature}</p>

      {/* Preview text */}
      <p className="flex-1 text-xs text-text-secondary line-clamp-3 leading-relaxed">
        {document.text}
      </p>

      {/* Footer: ID + Link icon */}
      <div className="flex items-center justify-between pt-2 border-t border-bg-border">
        <span className="text-xs text-text-muted">{document.id}</span>
        {document.url && (
          <ExternalLink className="h-3.5 w-3.5 text-text-muted group-hover:text-accent transition-colors" />
        )}
      </div>
    </button>
  )
}
