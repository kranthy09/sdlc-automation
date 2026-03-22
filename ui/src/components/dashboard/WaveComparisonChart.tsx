import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { Batch } from '@/api/types'

interface WaveComparisonChartProps {
  batches: Batch[]
}

export function WaveComparisonChart({ batches }: WaveComparisonChartProps) {
  // Aggregate by wave
  const byWave = batches
    .filter((b) => b.status === 'complete')
    .reduce<Record<number, { fit: number; partial_fit: number; gap: number; wave: number }>>(
      (acc, b) => {
        const w = b.wave
        if (!acc[w]) acc[w] = { wave: w, fit: 0, partial_fit: 0, gap: 0 }
        acc[w].fit += b.summary.fit
        acc[w].partial_fit += b.summary.partial_fit
        acc[w].gap += b.summary.gap
        return acc
      },
      {},
    )

  const data = Object.values(byWave).sort((a, b) => a.wave - b.wave)

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border border-bg-border bg-bg-surface">
        <p className="text-sm text-text-muted">No completed batches to compare.</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface p-4">
      <p className="mb-3 text-sm font-medium text-text-secondary">Wave-over-Wave Comparison</p>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
          <XAxis
            dataKey="wave"
            tickFormatter={(v) => `W${v}`}
            tick={{ fill: '#64748b', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: 8,
              fontSize: 12,
            }}
            cursor={{ fill: '#1e293b' }}
            labelFormatter={(v) => `Wave ${v}`}
          />
          <Legend
            iconType="circle"
            iconSize={8}
            formatter={(value) => (
              <span style={{ color: '#94a3b8', fontSize: 12 }}>
                {value === 'fit' ? 'Fit' : value === 'partial_fit' ? 'Partial Fit' : 'Gap'}
              </span>
            )}
          />
          <Bar dataKey="fit" fill="#10b981" radius={[3, 3, 0, 0]} />
          <Bar dataKey="partial_fit" fill="#f59e0b" radius={[3, 3, 0, 0]} />
          <Bar dataKey="gap" fill="#ef4444" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
