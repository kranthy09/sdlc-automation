import { FileText, Table2, ImageIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ModalityBadgeProps {
  modality: 'TEXT' | 'TABLE' | 'IMAGE' | string
  size?: 'sm' | 'md'
}

/**
 * Reusable pill badge showing the modality (TEXT, TABLE, or IMAGE) of a requirement source.
 * Used in EvidencePanel, ArtifactGallery, and PhaseGatePanel.
 */
export function ModalityBadge({ modality, size = 'md' }: ModalityBadgeProps) {
  const isSmall = size === 'sm'
  const iconSize = isSmall ? 'h-3 w-3' : 'h-4 w-4'
  const padding = isSmall ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'

  const getIcon = () => {
    switch (modality) {
      case 'TEXT':
        return <FileText className={cn(iconSize, 'text-text-muted')} />
      case 'TABLE':
        return <Table2 className={cn(iconSize, 'text-amber-400')} />
      case 'IMAGE':
        return <ImageIcon className={cn(iconSize, 'text-blue-400')} />
      default:
        return null
    }
  }

  const getColors = () => {
    switch (modality) {
      case 'TEXT':
        return 'bg-bg-raised text-text-muted border-bg-border'
      case 'TABLE':
        return 'bg-amber-400/10 text-amber-400 border-amber-400/30'
      case 'IMAGE':
        return 'bg-blue-400/10 text-blue-400 border-blue-400/30'
      default:
        return 'bg-bg-raised text-text-muted border-bg-border'
    }
  }

  const label =
    modality === 'TEXT' || modality === 'TABLE' || modality === 'IMAGE'
      ? modality
      : modality.split('_').pop()?.toUpperCase() || modality

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border',
        padding,
        getColors(),
      )}
    >
      {getIcon()}
      <span className="font-medium">{label}</span>
    </div>
  )
}
