import { useNavigate } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/Button'

interface ReviewBannerProps {
  batchId: string
  reviewItems: number
  reasons: {
    low_confidence: number
    conflicts: number
    anomalies: number
  }
}

export function ReviewBanner({ batchId, reviewItems, reasons }: ReviewBannerProps) {
  const navigate = useNavigate()

  const breakdown = [
    reasons.low_confidence > 0 && `${reasons.low_confidence} low confidence`,
    reasons.conflicts > 0 && `${reasons.conflicts} conflict${reasons.conflicts > 1 ? 's' : ''}`,
    reasons.anomalies > 0 && `${reasons.anomalies} anomal${reasons.anomalies > 1 ? 'ies' : 'y'}`,
  ]
    .filter(Boolean)
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
