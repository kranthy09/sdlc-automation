import { useState } from 'react'
import { cn, formatConfidence } from '@/lib/utils'
import type { Classification, AtomJourney } from '@/api/types'
import { Badge } from '@/components/ui/Badge'

type TabKey = 'output' | 'classify' | 'match' | 'retrieve' | 'ingest'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'output', label: 'Output' },
  { key: 'classify', label: 'Classify' },
  { key: 'match', label: 'Match' },
  { key: 'retrieve', label: 'Retrieve' },
  { key: 'ingest', label: 'Ingest' },
]

const CONFIDENCE_COLOR: Record<string, string> = {
  HIGH: 'text-fit-text',
  MEDIUM: 'text-partial-text',
  LOW: 'text-gap-text',
}

const EFFORT_LABEL: Record<string, string> = { S: 'Small', M: 'Medium', L: 'Large' }

const ROUTE_COLOR: Record<string, string> = {
  FAST_TRACK: 'bg-fit-muted text-fit-text border-fit',
  DEEP_REASON: 'bg-partial-muted text-partial-text border-partial',
  GAP_CONFIRM: 'bg-gap-muted text-gap-text border-gap',
}

// ─── Signal bar ──────────────────────────────────────────────────────────────

function SignalBar({ label, value, weight }: { label: string; value: number; weight?: string }) {
  const pct = Math.round(value * 100)
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs">
        <span className="text-text-muted">{label}{weight && <span className="text-text-muted/60"> ({weight})</span>}</span>
        <span className="text-text-secondary font-medium">{formatConfidence(value)}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-bg-border/50">
        <div
          className="h-1.5 rounded-full bg-accent-glow/70"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// ─── Fallback panel (no journey data) ────────────────────────────────────────

interface FallbackProps {
  rationale: string
  d365Capability: string
  d365Navigation: string
  classification?: Classification
  configSteps?: string | null
  configurationSteps?: string[] | null
  gapDescription?: string | null
  devEffort?: 'S' | 'M' | 'L' | null
  gapType?: string | null
}

function FallbackPanel({ rationale, d365Capability, d365Navigation, classification, configSteps, configurationSteps, gapDescription, devEffort, gapType }: FallbackProps) {
  return (
    <div className="space-y-3 px-4 py-3">
      <div>
        <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">AI Rationale</p>
        <p className="text-sm text-text-secondary leading-relaxed">{rationale}</p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">D365 Capability</p>
          <p className="text-sm text-text-primary">{d365Capability}</p>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Navigation</p>
          <p className="font-mono text-xs text-accent-glow">{d365Navigation}</p>
        </div>
      </div>
      {classification === 'GAP' && gapDescription && (
        <div>
          <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Gap description</p>
          <p className="text-sm text-text-secondary">{gapDescription}</p>
        </div>
      )}
      {classification === 'PARTIAL_FIT' && configurationSteps && configurationSteps.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Configuration steps</p>
          <ol className="list-decimal list-inside space-y-0.5">
            {configurationSteps.map((step, i) => (
              <li key={i} className="text-sm text-text-secondary">{step}</li>
            ))}
          </ol>
        </div>
      )}
      {classification === 'PARTIAL_FIT' && configSteps && !configurationSteps?.length && (
        <div>
          <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Configuration steps</p>
          <p className="text-sm text-text-secondary">{configSteps}</p>
        </div>
      )}
      {devEffort && (
        <span className="text-xs text-text-muted">Dev effort: {EFFORT_LABEL[devEffort] ?? devEffort}</span>
      )}
      {gapType && (
        <span className="text-xs text-text-muted ml-3">Gap type: {gapType}</span>
      )}
    </div>
  )
}

// ─── Tab content renderers ───────────────────────────────────────────────────

function IngestTab({ journey }: { journey: AtomJourney }) {
  const d = journey.ingest
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span><span className="text-text-muted">Intent:</span> <span className="text-text-primary font-medium">{d.intent}</span></span>
        <span><span className="text-text-muted">Module:</span> <span className="text-text-primary">{d.module}</span></span>
        <span><span className="text-text-muted">Priority:</span> <span className="text-text-primary">{d.priority}</span></span>
        <span><span className="text-text-muted">Content:</span> <span className="text-text-primary">{d.content_type}</span></span>
      </div>
      {d.entity_hints.length > 0 && (
        <div>
          <p className="text-xs text-text-muted mb-1">Entity hints</p>
          <div className="flex flex-wrap gap-1.5">
            {d.entity_hints.map((h) => (
              <span key={h} className="rounded-full border border-bg-border bg-bg-raised px-2 py-0.5 text-xs text-text-secondary">{h}</span>
            ))}
          </div>
        </div>
      )}
      <div className="flex gap-6">
        <div>
          <p className="text-xs text-text-muted">Specificity</p>
          <p className="text-sm font-semibold text-text-primary">{formatConfidence(d.specificity_score)}</p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Completeness</p>
          <p className="text-sm font-semibold text-text-primary">{Math.round(d.completeness_score)}%</p>
        </div>
      </div>
      {d.source_refs.length > 0 && (
        <p className="text-xs text-text-muted">Source: {d.source_refs.join(', ')}</p>
      )}
    </div>
  )
}

function RetrieveTab({ journey }: { journey: AtomJourney }) {
  const d = journey.retrieve
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <p className="text-xs text-text-muted">Retrieval confidence</p>
        <span className={cn('text-sm font-semibold', CONFIDENCE_COLOR[d.retrieval_confidence])}>
          {d.retrieval_confidence}
        </span>
      </div>
      {d.capabilities.length > 0 && (
        <div>
          <p className="text-xs text-text-muted mb-1">Top capabilities</p>
          <div className="space-y-1">
            {d.capabilities.slice(0, 5).map((c) => (
              <div key={c.name} className="flex items-center gap-3 text-sm">
                <span className="font-medium text-text-primary w-12 shrink-0">{formatConfidence(c.score)}</span>
                <span className="text-text-secondary">{c.name}</span>
                <span className="font-mono text-xs text-accent-glow ml-auto">{c.navigation}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {d.ms_learn_refs.length > 0 && (
        <div>
          <p className="text-xs text-text-muted mb-1">MS Learn references</p>
          <div className="space-y-0.5">
            {d.ms_learn_refs.slice(0, 3).map((r) => (
              <div key={r.title} className="flex items-center gap-3 text-sm">
                <span className="text-text-muted w-12 shrink-0">{formatConfidence(r.score)}</span>
                <span className="text-text-secondary">{r.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {d.prior_fitments.length > 0 && (
        <div>
          <p className="text-xs text-text-muted mb-1">Prior fitments</p>
          <div className="flex flex-wrap gap-2">
            {d.prior_fitments.map((pf, i) => (
              <div key={i} className="flex items-center gap-1.5 rounded-full border border-bg-border bg-bg-raised px-2.5 py-1">
                <span className="text-xs text-text-muted">Wave {pf.wave} · {pf.country}</span>
                <Badge variant={pf.classification as Classification} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function MatchTab({ journey }: { journey: AtomJourney }) {
  const d = journey.match
  const signals = d.signal_breakdown
  const weights: Record<string, string> = {
    embedding_cosine: '0.25',
    entity_overlap: '0.20',
    token_ratio: '0.15',
    historical_alignment: '0.25',
    rerank_score: '0.15',
  }
  const signalLabels: Record<string, string> = {
    embedding_cosine: 'Embedding cosine',
    entity_overlap: 'Entity overlap',
    token_ratio: 'Token ratio',
    historical_alignment: 'Historical alignment',
    rerank_score: 'Rerank score',
  }
  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {Object.entries(signals).map(([key, val]) => (
          <SignalBar key={key} label={signalLabels[key] ?? key} value={val} weight={weights[key]} />
        ))}
      </div>
      <div className="flex items-center gap-6">
        <div>
          <p className="text-xs text-text-muted">Composite score</p>
          <p className="text-sm font-semibold text-text-primary">{formatConfidence(d.composite_score)}</p>
        </div>
      </div>
      {d.anomaly_flags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {d.anomaly_flags.map((f) => (
            <span key={f} className="rounded-full border border-partial bg-partial-muted/30 px-2 py-0.5 text-xs text-partial-text">{f}</span>
          ))}
        </div>
      )}
    </div>
  )
}

function ClassifyTab({ journey }: { journey: AtomJourney }) {
  const d = journey.classify
  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">AI Rationale</p>
        <p className="text-sm text-text-secondary leading-relaxed">{d.rationale}</p>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <div>
          <p className="text-xs text-text-muted">LLM calls</p>
          <p className="text-sm font-medium text-text-primary">{d.llm_calls_used}</p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Confidence</p>
          <p className="text-sm font-semibold text-text-primary">{formatConfidence(d.confidence)}</p>
        </div>
      </div>
      {d.d365_capability && (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">D365 Capability</p>
            <p className="text-sm text-text-primary">{d.d365_capability}</p>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Navigation</p>
            <p className="font-mono text-xs text-accent-glow">{d.d365_navigation}</p>
          </div>
        </div>
      )}
    </div>
  )
}

function OutputTab({ journey }: { journey: AtomJourney }) {
  const d = journey.output
  const cls = d.classification
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4">
        <Badge variant={cls} />
        <span className="text-sm font-semibold text-text-primary">{formatConfidence(d.confidence)}</span>
        {d.reviewer_override && (
          <span className="rounded-full border border-partial/30 bg-partial-muted/30 px-1.5 py-0.5 text-[10px] text-partial-text">
            Overridden
          </span>
        )}
      </div>

      {cls === 'FIT' && journey.classify.d365_capability && (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">D365 Capability</p>
            <p className="text-sm text-text-primary">{journey.classify.d365_capability}</p>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Navigation</p>
            <p className="font-mono text-xs text-accent-glow">{journey.classify.d365_navigation}</p>
          </div>
        </div>
      )}

      {cls === 'PARTIAL_FIT' && d.configuration_steps && d.configuration_steps.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Configuration steps</p>
          <ol className="list-decimal list-inside space-y-0.5">
            {d.configuration_steps.map((step, i) => (
              <li key={i} className="text-sm text-text-secondary">{step}</li>
            ))}
          </ol>
        </div>
      )}
      {cls === 'PARTIAL_FIT' && d.config_steps && !d.configuration_steps?.length && (
        <div>
          <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Configuration steps</p>
          <p className="text-sm text-text-secondary">{d.config_steps}</p>
        </div>
      )}

      {cls === 'GAP' && (
        <div className="grid grid-cols-3 gap-4">
          {d.gap_description && (
            <div className="col-span-2">
              <p className="mb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Gap description</p>
              <p className="text-sm text-text-secondary leading-relaxed">{d.gap_description}</p>
            </div>
          )}
          {(d.gap_type || d.dev_effort) && (
            <div className="space-y-2">
              {d.gap_type && (
                <div>
                  <p className="text-xs text-text-muted">Gap type</p>
                  <p className="text-sm font-medium text-gap-text">{d.gap_type}</p>
                </div>
              )}
              {d.dev_effort && (
                <div>
                  <p className="text-xs text-text-muted">Dev effort</p>
                  <p className="text-sm font-medium text-text-primary">{EFFORT_LABEL[d.dev_effort] ?? d.dev_effort}</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main component ──────────────────────────────────────────────────────────

export interface EvidencePanelProps {
  // Journey data (preferred — full phase tabs)
  journey?: AtomJourney | null
  // Fallback props (used when journey hasn't loaded yet)
  rationale: string
  d365Capability: string
  d365Navigation: string
  classification?: Classification
  configSteps?: string | null
  configurationSteps?: string[] | null
  gapDescription?: string | null
  devEffort?: 'S' | 'M' | 'L' | null
  gapType?: string | null
}

const TAB_CONTENT: Record<TabKey, (j: AtomJourney) => JSX.Element> = {
  ingest: (j) => <IngestTab journey={j} />,
  retrieve: (j) => <RetrieveTab journey={j} />,
  match: (j) => <MatchTab journey={j} />,
  classify: (j) => <ClassifyTab journey={j} />,
  output: (j) => <OutputTab journey={j} />,
}

export function EvidencePanel(props: EvidencePanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('output')

  if (!props.journey) {
    return (
      <FallbackPanel
        rationale={props.rationale}
        d365Capability={props.d365Capability}
        d365Navigation={props.d365Navigation}
        classification={props.classification}
        configSteps={props.configSteps}
        configurationSteps={props.configurationSteps}
        gapDescription={props.gapDescription}
        devEffort={props.devEffort}
        gapType={props.gapType}
      />
    )
  }

  return (
    <div className="px-4 py-3">
      {/* Tab bar */}
      <div className="flex gap-1 border-b border-bg-border/50 mb-3">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              'px-3 py-1.5 text-xs font-medium rounded-t transition-colors',
              activeTab === tab.key
                ? 'text-accent-glow border-b-2 border-accent-glow bg-bg-raised/50'
                : 'text-text-muted hover:text-text-secondary',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {TAB_CONTENT[activeTab](props.journey)}
    </div>
  )
}
