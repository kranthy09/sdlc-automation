import { useCallback, useState } from 'react'
import { Upload, FileText, X } from 'lucide-react'
import { cn, formatBytes } from '@/lib/utils'

const ACCEPTED = ['.xlsx', '.docx', '.pdf', '.txt']
const ACCEPTED_MIME = [
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/pdf',
  'text/plain',
]

interface DropZoneProps {
  file: File | null
  onFile: (f: File) => void
  onClear: () => void
  disabled?: boolean
}

export function DropZone({ file, onFile, onClear, disabled }: DropZoneProps) {
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const validate = (f: File): boolean => {
    const ext = '.' + f.name.split('.').pop()?.toLowerCase()
    if (!ACCEPTED.includes(ext) && !ACCEPTED_MIME.includes(f.type)) {
      setError(`Unsupported format. Use: ${ACCEPTED.join(', ')}`)
      return false
    }
    if (f.size > 50 * 1024 * 1024) {
      setError('File too large. Max 50 MB.')
      return false
    }
    setError(null)
    return true
  }

  const handleFile = (f: File) => {
    if (validate(f)) onFile(f)
  }

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      if (disabled) return
      const f = e.dataTransfer.files[0]
      if (f) handleFile(f)
    },
    [disabled],
  )

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) handleFile(f)
    e.target.value = ''
  }

  if (file) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-fit/30 bg-fit-muted/20 px-4 py-3">
        <FileText className="h-8 w-8 shrink-0 text-fit-text" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-text-primary">{file.name}</p>
          <p className="text-xs text-text-muted">{formatBytes(file.size)}</p>
        </div>
        {!disabled && (
          <button
            onClick={onClear}
            className="shrink-0 rounded p-1 text-text-muted hover:text-text-primary transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    )
  }

  return (
    <div>
      <label
        className={cn(
          'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors',
          dragging
            ? 'border-accent bg-accent/5'
            : 'border-bg-border hover:border-accent/50 hover:bg-bg-raised/50',
          disabled && 'pointer-events-none opacity-50',
        )}
        onDragEnter={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={(e) => { e.preventDefault(); setDragging(false) }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
      >
        <Upload className={cn('h-8 w-8', dragging ? 'text-accent' : 'text-text-muted')} />
        <div>
          <p className="text-sm font-medium text-text-primary">
            Drop file here or <span className="text-accent">browse</span>
          </p>
          <p className="mt-1 text-xs text-text-muted">{ACCEPTED.join(', ')} · max 50 MB</p>
        </div>
        <input
          type="file"
          className="sr-only"
          accept={ACCEPTED.join(',')}
          onChange={onInputChange}
          disabled={disabled}
        />
      </label>
      {error && <p className="mt-2 text-xs text-gap-text">{error}</p>}
    </div>
  )
}
