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
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-bg-border)" />
          <XAxis type="number" stroke="var(--color-text-muted)" style={{ fontSize: '12px' }} />
          <YAxis dataKey="name" type="category" stroke="var(--color-text-muted)" style={{ fontSize: '12px' }} />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--color-bg-surface)',
              border: '1px solid var(--color-bg-border)',
              borderRadius: '8px',
            }}
            labelStyle={{ color: 'var(--color-text-primary)' }}
            formatter={(value: number) => formatTime(value)}
          />
          <Bar dataKey="latency" fill="var(--color-accent)" name="Duration (seconds)" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
