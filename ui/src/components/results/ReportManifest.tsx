import { Download, FileText, FileJson, File } from 'lucide-react'
import { Button } from '@/components/ui/Button'

interface ReportFile {
  name: string
  type: 'csv' | 'json' | 'pdf' | 'xlsx'
  size: string
  description: string
}

interface ReportManifestProps {
  batchId: string
  onDownload?: (fileType: string) => void
}

const REPORT_FILES: ReportFile[] = [
  {
    name: 'Results Export',
    type: 'csv',
    size: 'Varies',
    description: 'All requirements and classifications in CSV format, suitable for Excel or data analysis',
  },
  {
    name: 'Detailed Report',
    type: 'json',
    size: 'Varies',
    description: 'Complete journey data for each atom in JSON format with full signal breakdown',
  },
  {
    name: 'Executive Summary',
    type: 'pdf',
    size: '~2MB',
    description: 'PDF summary with charts, metrics, and high-level findings',
  },
  {
    name: 'Excel Workbook',
    type: 'xlsx',
    size: 'Varies',
    description: 'Multi-sheet workbook with results, charts, and module breakdown',
  },
]

const ICON_MAP: Record<string, React.ReactNode> = {
  csv: <FileText className="h-4 w-4" />,
  json: <FileJson className="h-4 w-4" />,
  pdf: <FileText className="h-4 w-4" />,
  xlsx: <File className="h-4 w-4" />,
}

export function ReportManifest({ batchId, onDownload }: ReportManifestProps) {
  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-5">
      <p className="mb-4 text-xs font-medium text-text-muted uppercase tracking-wide">
        Available Reports
      </p>

      <div className="grid grid-cols-2 gap-3">
        {REPORT_FILES.map((file) => (
          <div
            key={file.type}
            className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3 flex items-start justify-between"
          >
            <div className="flex items-start gap-3 flex-1">
              <div className="mt-1 text-text-muted">{ICON_MAP[file.type]}</div>
              <div className="flex-1">
                <p className="text-sm font-medium text-text-primary">{file.name}</p>
                <p className="text-xs text-text-muted mt-0.5">{file.description}</p>
                <p className="text-xs text-text-muted/60 mt-1">{file.size}</p>
              </div>
            </div>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onDownload?.(file.type)}
              className="ml-2 shrink-0"
            >
              <Download className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-lg border border-bg-border/50 bg-bg-raised/50 px-3 py-2">
        <p className="text-xs text-text-muted">
          💡 <span className="ml-1">Tip: CSV exports are ideal for importing to other systems. JSON includes full pipeline metadata for archival purposes.</span>
        </p>
      </div>
    </div>
  )
}
