import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import type { ResultsSummary } from '@/api/types'

interface DistributionChartProps {
  summary: ResultsSummary
  total: number
}

const SEGMENTS = [
  { key: 'fit' as const, label: 'Fit', color: '#10b981' },
  { key: 'partial_fit' as const, label: 'Partial Fit', color: '#f59e0b' },
  { key: 'gap' as const, label: 'Gap', color: '#ef4444' },
]

export function DistributionChart({ summary, total }: DistributionChartProps) {
  const data = SEGMENTS.map((s) => ({
    name: s.label,
    value: summary[s.key],
    color: s.color,
    pct: total > 0 ? Math.round((summary[s.key] / total) * 100) : 0,
  })).filter((d) => d.value > 0)

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface p-4">
      <p className="mb-3 text-sm font-medium text-text-secondary">Classification Distribution</p>
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={60}
            outerRadius={90}
            paddingAngle={2}
            dataKey="value"
          >
            {data.map((entry) => (
              <Cell key={entry.name} fill={entry.color} stroke="transparent" />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(value: number, name: string) => [
              `${value} (${data.find((d) => d.name === name)?.pct}%)`,
              name,
            ]}
          />
          <Legend
            iconType="circle"
            iconSize={8}
            formatter={(value) => (
              <span style={{ color: '#94a3b8', fontSize: 12 }}>{value}</span>
            )}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
