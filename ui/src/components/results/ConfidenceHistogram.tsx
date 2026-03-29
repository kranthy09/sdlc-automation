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
    FIT: '#10b981',      // emerald-500
    PARTIAL_FIT: '#f59e0b', // amber-500
    GAP: '#ef4444',      // red-500
  }

  return (
    <div className="w-full h-80">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bins} margin={{ top: 20, right: 30, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
          <XAxis
            dataKey="bin"
            tick={{ fill: '#e2e8f0', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: '#e2e8f0', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#0f172a',
              border: '1px solid #334155',
              borderRadius: '8px',
              fontSize: 12,
            }}
            labelStyle={{ color: '#e2e8f0', fontWeight: 'bold' }}
            formatter={(value: number) => value.toString()}
            itemStyle={{ color: '#e2e8f0' }}
            cursor={{ fill: '#1e293b' }}
          />
          <Legend
            wrapperStyle={{ paddingTop: '20px' }}
            formatter={(value) => (
              <span style={{ color: '#e2e8f0', fontSize: 12 }}>
                {value === 'FIT' ? 'Fit' : value === 'PARTIAL_FIT' ? 'Partial Fit' : 'Gap'}
              </span>
            )}
            iconType="circle"
            iconSize={8}
          />
          <Bar dataKey="FIT" fill={colorMap.FIT} name="FIT" radius={[3, 3, 0, 0]} />
          <Bar dataKey="PARTIAL_FIT" fill={colorMap.PARTIAL_FIT} name="PARTIAL_FIT" radius={[3, 3, 0, 0]} />
          <Bar dataKey="GAP" fill={colorMap.GAP} name="GAP" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
