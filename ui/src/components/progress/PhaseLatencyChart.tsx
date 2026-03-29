import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import type { PhaseProgressItem } from '@/api/types'

interface PhaseLatencyChartProps {
  phases: PhaseProgressItem[]
}

const phaseNames: Record<number, string> = {
  1: 'Ingest',
  2: 'Retrieve',
  3: 'Match',
  4: 'Classify',
  5: 'Validate',
}

export function PhaseLatencyChart({ phases }: PhaseLatencyChartProps) {
  const completedPhases = phases.filter((p) => p.status === 'complete' && p.latency_ms !== null)

  if (completedPhases.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center text-text-muted text-sm">
        No completed phases yet
      </div>
    )
  }

  const data = completedPhases.map((p) => ({
    phase: `Phase ${p.phase}`,
    name: phaseNames[p.phase] || `Phase ${p.phase}`,
    latency: Math.round((p.latency_ms || 0) / 1000), // Convert to seconds
  }))

  const formatTime = (ms: number) => {
    const secs = ms
    if (secs < 60) return `${secs}s`
    const mins = Math.floor(secs / 60)
    const sec = secs % 60
    return `${mins}m ${sec}s`
  }

  return (
    <div className="w-full h-80">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 20, right: 30, left: 120, bottom: 20 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
          <XAxis
            type="number"
            tick={{ fill: '#e2e8f0', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            dataKey="name"
            type="category"
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
            itemStyle={{ color: '#e2e8f0' }}
            cursor={{ fill: '#1e293b' }}
            formatter={(value: number) => formatTime(value)}
          />
          <Bar dataKey="latency" fill="#3b82f6" name="Duration (seconds)" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
