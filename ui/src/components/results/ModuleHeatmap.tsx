import { cn } from '@/lib/utils'
import type { ResultsSummary } from '@/api/types'

interface ModuleHeatmapProps {
  summary: ResultsSummary
  onModuleClick?: (module: string) => void
}

export function ModuleHeatmap({ summary, onModuleClick }: ModuleHeatmapProps) {
  const modules = Object.entries(summary.by_module || {})
    .sort((a, b) => {
      const rateA = (a[1].fit / (a[1].fit + a[1].partial_fit + a[1].gap)) * 100
      const rateB = (b[1].fit / (b[1].fit + b[1].partial_fit + b[1].gap)) * 100
      return rateB - rateA
    })

  const getFitRateColor = (rate: number): string => {
    if (rate >= 80) return 'bg-fit-muted text-fit-text'
    if (rate >= 50) return 'bg-partial-muted text-partial-text'
    return 'bg-gap-muted text-gap-text'
  }

  return (
    <div className="space-y-2">
      <div className="grid gap-2">
        {modules.map(([module, counts]) => {
          const total = counts.fit + counts.partial_fit + counts.gap
          const fitRate = (counts.fit / total) * 100
          return (
            <button
              key={module}
              onClick={() => onModuleClick?.(module)}
              className="w-full text-left p-3 rounded-lg border border-bg-border hover:bg-bg-raised/50 transition-colors group"
            >
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-text-primary truncate group-hover:text-accent transition-colors">
                    {module}
                  </p>
                  <p className="text-xs text-text-muted">
                    {total} atom{total !== 1 ? 's' : ''}
                  </p>
                </div>
                <div className={cn('px-2 py-1 rounded font-semibold text-xs whitespace-nowrap', getFitRateColor(fitRate))}>
                  {Math.round(fitRate)}% fit
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="flex-1 flex gap-1 h-2 rounded-full overflow-hidden bg-bg-border/30">
                  <div className="bg-fit" style={{ width: `${(counts.fit / total) * 100}%` }} />
                  <div className="bg-partial" style={{ width: `${(counts.partial_fit / total) * 100}%` }} />
                  <div className="bg-gap" style={{ width: `${(counts.gap / total) * 100}%` }} />
                </div>
                <div className="flex gap-2 text-xs text-text-muted min-w-fit">
                  <span><span className="text-fit-text font-medium">{counts.fit}</span> fit</span>
                  <span><span className="text-partial-text font-medium">{counts.partial_fit}</span> partial</span>
                  <span><span className="text-gap-text font-medium">{counts.gap}</span> gap</span>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
