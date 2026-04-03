import { useNavigate } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/Button'

interface ReviewBannerProps {
  batchId: string
  reviewItems: number
  reasons: {
    low_confidence?: number
    anomaly?: number
    pii_detected?: number
    gap_review?: number
    partial_fit_no_config?: number
  }
}

const REASON_LABELS: Record<keyof Exclude<ReviewBannerProps['reasons'], undefined>, string> = {
  low_confidence: 'low confidence',
  anomaly: 'anomaly',
  pii_detected: 'PII detected',
  gap_review: 'gap review',
  partial_fit_no_config: 'missing config',
}

export function ReviewBanner({ batchId, reviewItems, reasons }: ReviewBannerProps) {
  const navigate = useNavigate()

  const breakdown = (
    Object.entries(reasons) as Array<[keyof typeof REASON_LABELS, number | undefined]>
  )
    .filter(([_, count]) => (count ?? 0) > 0)
    .map(([reason, count]) => `${count} ${REASON_LABELS[reason]}`)
    .join(' · ')

  return (
    <div className="flex items-center gap-4 rounded-xl border border-partial/30 bg-partial-muted/20 px-5 py-4">
      <AlertTriangle className="h-5 w-5 shrink-0 text-partial-text" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-partial-text">
          {reviewItems} item{reviewItems !== 1 ? 's' : ''} need your review before pipeline can
          complete
        </p>
        {breakdown && <p className="mt-0.5 text-xs text-text-muted">{breakdown}</p>}
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => navigate(`/review/${batchId}`)}
        className="shrink-0 border-partial/30 text-partial-text hover:bg-partial-muted/30"
      >
        Review now
      </Button>
    </div>
  )
}
