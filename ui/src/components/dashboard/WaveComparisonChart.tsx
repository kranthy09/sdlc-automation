import { useState } from 'react'
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { cn } from '@/lib/utils'
import type { Batch } from '@/api/types'

type ChartView = 'counts' | 'confidence' | 'modules'

interface WaveComparisonChartProps {
  batches: Batch[]
}

export function WaveComparisonChart({ batches }: WaveComparisonChartProps) {
  const [view, setView] = useState<ChartView>('counts')

  const completedBatches = batches.filter((b) => b.status === 'complete')

  // Aggregate by wave
  const byWave = completedBatches.reduce<Record<number, { fit: number; partial_fit: number; gap: number; wave: number }>>(
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

  const countData = Object.values(byWave).sort((a, b) => a.wave - b.wave)

  // Confidence trends
  const confidenceData = completedBatches
    .sort((a, b) => a.wave - b.wave)
    .map((b) => ({
      wave: b.wave,
      batch: b.upload_filename.substring(0, 15),
      fit_rate: b.summary.fit / b.summary.fit + b.summary.partial_fit + b.summary.gap || 0,
    }))
    .slice(-10)

  // Module distribution
  const moduleData = Object.entries(
    completedBatches.reduce<Record<string, { fit: number; partial_fit: number; gap: number }>>(
      (acc, b) => {
        Object.entries(b.summary).forEach(([key]) => {
          if (!acc[key]) acc[key] = { fit: 0, partial_fit: 0, gap: 0 }
        })
        return acc
      },
      {},
    ),
  ).slice(0, 5)

  if (countData.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border border-bg-border bg-bg-surface">
        <p className="text-sm text-text-muted">No completed batches to compare.</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface p-4">
      {/* Header with tabs */}
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-medium text-text-secondary">Wave Analysis</p>
        <div className="flex gap-2">
          {(['counts', 'confidence', 'modules'] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={cn(
                'px-3 py-1.5 text-xs font-medium rounded transition-colors',
                view === v
                  ? 'bg-accent text-white'
                  : 'bg-bg-raised text-text-secondary hover:text-text-primary'
              )}
            >
              {v === 'counts' ? 'Counts' : v === 'confidence' ? 'Confidence' : 'Modules'}
            </button>
          ))}
        </div>
      </div>

      {/* Charts */}
      <ResponsiveContainer width="100%" height={240}>
        {view === 'counts' && (
          <BarChart data={countData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
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
        )}

        {view === 'confidence' && (
          <LineChart data={confidenceData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis
              dataKey="batch"
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
              formatter={(value: number) => `${Math.round(value * 100)}%`}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="fit_rate"
              stroke="#10b981"
              name="Fit Rate"
              strokeWidth={2}
              dot={{ fill: '#10b981', r: 4 }}
            />
          </LineChart>
        )}

        {view === 'modules' && (
          <BarChart data={moduleData.map(([name, data]) => ({ name, ...data }))} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis
              dataKey="name"
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
        )}
      </ResponsiveContainer>
    </div>
  )
}
