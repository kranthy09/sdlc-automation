import { Progress } from '@/components/ui/Progress'

interface ReviewProgressProps {
  reviewed: number
  total: number
}

export function ReviewProgress({ reviewed, total }: ReviewProgressProps) {
  const pct = total > 0 ? Math.round((reviewed / total) * 100) : 0

  return (
    <div className="flex items-center gap-4 rounded-xl border border-bg-border bg-bg-surface px-4 py-3">
      <div className="flex-1">
        <div className="mb-1.5 flex justify-between text-xs">
          <span className="font-medium text-text-primary">{reviewed} of {total} reviewed</span>
          <span className="text-text-muted">{pct}%</span>
        </div>
        <Progress value={pct} color={reviewed === total ? 'fit' : 'accent'} />
      </div>
    </div>
  )
}
