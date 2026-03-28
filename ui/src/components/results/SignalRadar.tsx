import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, ResponsiveContainer, Tooltip } from 'recharts'
import type { SignalBreakdown } from '@/api/types'

interface SignalRadarProps {
  signals: SignalBreakdown
  compositeScore: number
}

export function SignalRadar({ signals, compositeScore }: SignalRadarProps) {
  const data = [
    {
      name: 'Embedding Cosine',
      value: Math.round(signals.embedding_cosine * 100),
      weight: 0.25,
    },
    {
      name: 'Entity Overlap',
      value: Math.round(signals.entity_overlap * 100),
      weight: 0.2,
    },
    {
      name: 'Token Ratio',
      value: Math.round(signals.token_ratio * 100),
      weight: 0.15,
    },
    {
      name: 'Historical Alignment',
      value: Math.round(signals.historical_alignment * 100),
      weight: 0.25,
    },
    {
      name: 'Rerank Score',
      value: Math.round(signals.rerank_score * 100),
      weight: 0.15,
    },
  ]

  return (
    <div className="relative w-full h-80 flex items-center justify-center">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data}>
          <PolarGrid stroke="var(--color-bg-border)" />
          <PolarAngleAxis dataKey="name" stroke="var(--color-text-muted)" style={{ fontSize: '11px' }} />
          <PolarRadiusAxis stroke="var(--color-text-muted)" angle={90} domain={[0, 100]} />
          <Radar
            name="Score"
            dataKey="value"
            stroke="var(--color-accent-glow)"
            fill="var(--color-accent-glow)"
            fillOpacity={0.25}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--color-bg-surface)',
              border: '1px solid var(--color-bg-border)',
              borderRadius: '8px',
            }}
            labelStyle={{ color: 'var(--color-text-primary)' }}
            formatter={(value: number) => `${value}%`}
          />
        </RadarChart>
      </ResponsiveContainer>

      {/* Center composite score */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="text-center">
          <p className="text-xs text-text-muted mb-1">Composite</p>
          <p className="text-2xl font-bold text-accent-glow">{Math.round(compositeScore * 100)}%</p>
        </div>
      </div>
    </div>
  )
}
