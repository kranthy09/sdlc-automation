import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts'
import type { FitmentResult, Classification } from '@/api/types'

interface ConfidenceHistogramProps {
  results: FitmentResult[]
}

interface BinData {
  bin: string
  FIT: number
  PARTIAL_FIT: number
  GAP: number
  dominant: Classification
}

export function ConfidenceHistogram({ results }: ConfidenceHistogramProps) {
  // Create 10 bins for confidence ranges: 0-10%, 10-20%, ..., 90-100%
  const bins: BinData[] = Array.from({ length: 10 }, (_, i) => ({
    bin: `${i * 10}-${(i + 1) * 10}%`,
    FIT: 0,
    PARTIAL_FIT: 0,
    GAP: 0,
    dominant: 'FIT' as Classification,
  }))

  // Distribute results into bins
  for (const result of results) {
    const binIndex = Math.min(Math.floor(result.confidence * 10), 9)
    bins[binIndex][result.classification]++
  }

  // Calculate dominant classification per bin
  for (const bin of bins) {
    const max = Math.max(bin.FIT, bin.PARTIAL_FIT, bin.GAP)
    if (max === 0) {
      bin.dominant = 'FIT'
    } else if (bin.FIT === max) {
      bin.dominant = 'FIT'
    } else if (bin.PARTIAL_FIT === max) {
      bin.dominant = 'PARTIAL_FIT'
    } else {
      bin.dominant = 'GAP'
    }
  }

  const colorMap: Record<Classification, string> = {
    FIT: '#22c55e',
    PARTIAL_FIT: '#f59e0b',
    GAP: '#ef4444',
  }

  return (
    <div className="w-full h-80">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bins} margin={{ top: 20, right: 30, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-bg-border)" />
          <XAxis dataKey="bin" stroke="var(--color-text-muted)" style={{ fontSize: '12px' }} />
          <YAxis stroke="var(--color-text-muted)" style={{ fontSize: '12px' }} />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--color-bg-surface)',
              border: '1px solid var(--color-bg-border)',
              borderRadius: '8px',
            }}
            labelStyle={{ color: 'var(--color-text-primary)' }}
          />
          <Legend wrapperStyle={{ paddingTop: '20px' }} />
          <Bar dataKey="FIT" fill={colorMap.FIT} name="Fit" />
          <Bar dataKey="PARTIAL_FIT" fill={colorMap.PARTIAL_FIT} name="Partial Fit" />
          <Bar dataKey="GAP" fill={colorMap.GAP} name="Gap" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
