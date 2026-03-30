import { useState } from 'react'
import { ChevronDown, ChevronRight, ShieldCheck } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import type { AtomJourney, Classification } from '@/api/types'

interface FeatureReportCardProps {
  journey: AtomJourney
  index: number
}

const CLASSIFICATION_BORDER: Record<Classification, string> = {
  FIT: 'border-l-4 border-l-fit',
  PARTIAL_FIT: 'border-l-4 border-l-partial',
  GAP: 'border-l-4 border-l-gap',
}

const CONFIDENCE_BADGE: Record<string, string> = {
  HIGH: 'bg-fit-muted text-fit-text border-fit/30',
  MEDIUM: 'bg-partial-muted text-partial-text border-partial/30',
  LOW: 'bg-gap-muted text-gap-text border-gap/30',
}

const ROUTE_BADGE: Record<string, string> = {
  FAST_TRACK: 'bg-fit-muted text-fit-text border-fit/30',
  DEEP_REASON: 'bg-partial-muted text-partial-text border-partial/30',
  GAP_CONFIRM: 'bg-gap-muted text-gap-text border-gap/30',
}

const DEV_EFFORT_BADGE: Record<string, string> = {
  S: 'bg-fit-muted text-fit-text border-fit/30',
  M: 'bg-partial-muted text-partial-text border-partial/30',
  L: 'bg-gap-muted text-gap-text border-gap/30',
}

const DEV_EFFORT_LABEL: Record<string, string> = {
  S: 'Small',
  M: 'Medium',
  L: 'Large',
}

const SIGNAL_LABELS: Record<string, string> = {
  embedding_cosine: 'Embedding Similarity',
  entity_overlap: 'Entity Overlap',
  token_ratio: 'Token Match',
  historical_alignment: 'Historical Alignment',
  rerank_score: 'Rerank Score',
}

export function FeatureReportCard({ journey, index }: FeatureReportCardProps) {
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [trailOpen, setTrailOpen] = useState(false)

  const { ingest, retrieve, match, classify, output } = journey
  const finalClass = output.classification
  const configSteps = output.configuration_steps ?? (output.config_steps ? [output.config_steps] : [])
  const hints = ingest.entity_hints?.slice(0, 8) ?? []
  const extraHints = (ingest.entity_hints?.length ?? 0) - 8

  return (
    <div className={`rounded-xl border border-border bg-surface ${CLASSIFICATION_BORDER[finalClass] ?? ''}`}>
      {/* ── Header row ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 px-4 pt-4 pb-3">
        <span className="min-w-[24px] text-center text-xs font-bold text-text-muted">
          {String(index).padStart(2, '0')}
        </span>

        <span className="rounded border border-border bg-bg-raised px-2 py-0.5 text-[11px] font-medium text-text-secondary">
          {ingest.module}
        </span>

        <span className="rounded border border-border bg-bg-raised px-2 py-0.5 text-[11px] text-text-muted">
          {ingest.intent}
        </span>

        <span className="rounded border border-border bg-bg-raised px-2 py-0.5 text-[11px] text-text-muted">
          {ingest.priority}
        </span>

        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${CONFIDENCE_BADGE[retrieve.retrieval_confidence] ?? ''}`}
        >
          {retrieve.retrieval_confidence}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {output.reviewer_override && (
            <span className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent-glow">
              <ShieldCheck className="h-3 w-3" />
              Consultant Override
            </span>
          )}
          <span className="text-[11px] text-text-muted">{ingest.atom_id}</span>
        </div>
      </div>

      {/* ── Requirement text ───────────────────────────────────────── */}
      <div className="px-4 pb-3">
        <p className="text-sm text-text leading-relaxed">{ingest.requirement_text}</p>
      </div>

      {/* ── Entity hints ───────────────────────────────────────────── */}
      {hints.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-4 pb-3">
          <span className="text-[10px] uppercase tracking-wide text-text-muted">Keywords:</span>
          {hints.map((h) => (
            <span
              key={h}
              className="rounded border border-border bg-bg-raised px-1.5 py-0.5 text-[11px] text-text-secondary"
            >
              {h}
            </span>
          ))}
          {extraHints > 0 && (
            <span className="text-[11px] text-text-muted">+{extraHints} more</span>
          )}
        </div>
      )}

      {/* ── Fitment decision block ─────────────────────────────────── */}
      <div className="mx-4 mb-3 rounded-lg border border-border bg-bg-raised p-3 space-y-2">
        {/* Classification + confidence + capability */}
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={finalClass} />
          <span className="text-sm font-semibold text-text">
            {Math.round(output.confidence * 100)}%
          </span>
          {classify.d365_capability && (
            <>
              <span className="text-text-muted">·</span>
              <span className="text-xs font-medium text-text-secondary">{classify.d365_capability}</span>
            </>
          )}
          {classify.d365_navigation && (
            <span className="ml-auto text-[11px] text-text-muted">{classify.d365_navigation}</span>
          )}
        </div>

        {/* Rationale */}
        {classify.rationale && (
          <p className="border-l-2 border-border pl-3 text-xs italic text-text-secondary leading-relaxed">
            {classify.rationale}
          </p>
        )}

        {/* PARTIAL_FIT: configuration steps */}
        {finalClass === 'PARTIAL_FIT' && (
          <div className="pt-1">
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-partial-text">
              Configuration Steps
            </p>
            {configSteps.length > 0 ? (
              <ol className="space-y-1 pl-4">
                {configSteps.map((step, i) => (
                  <li key={i} className="text-xs text-text-secondary list-decimal">
                    {step}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-xs italic text-text-muted">
                Configuration steps were not generated by the LLM for this requirement.
              </p>
            )}
          </div>
        )}

        {/* GAP: gap details */}
        {finalClass === 'GAP' && (
          <div className="pt-1 space-y-1.5">
            {output.gap_type && output.dev_effort && (
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-text-muted">Type:</span>
                <span className="text-xs font-medium text-text-secondary">{output.gap_type}</span>
                <span
                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${DEV_EFFORT_BADGE[output.dev_effort] ?? ''}`}
                >
                  Dev Effort: {DEV_EFFORT_LABEL[output.dev_effort] ?? output.dev_effort}
                </span>
              </div>
            )}
            {output.gap_description && (
              <p className="text-xs text-text-secondary leading-relaxed">{output.gap_description}</p>
            )}
          </div>
        )}
      </div>

      {/* ── Accordions ─────────────────────────────────────────────── */}
      <div className="border-t border-border">
        {/* Evidence accordion */}
        <button
          onClick={() => setEvidenceOpen((v) => !v)}
          className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs font-medium text-text-secondary hover:text-text transition-colors"
        >
          {evidenceOpen ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0" />
          )}
          Evidence & History
        </button>

        {evidenceOpen && (
          <div className="px-4 pb-4 space-y-3">
            {/* Top capabilities */}
            {retrieve.capabilities.length > 0 && (
              <div>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                  Top D365 Capabilities
                </p>
                <div className="space-y-1">
                  {retrieve.capabilities.slice(0, 3).map((cap) => (
                    <div key={cap.name} className="flex items-center gap-2">
                      <span className="w-40 shrink-0 truncate text-xs text-text-secondary">{cap.name}</span>
                      <div className="h-1.5 flex-1 rounded-full bg-bg-raised">
                        <div
                          className="h-1.5 rounded-full bg-accent/60"
                          style={{ width: `${Math.round(cap.score * 100)}%` }}
                        />
                      </div>
                      <span className="w-10 text-right text-[11px] text-text-muted">
                        {Math.round(cap.score * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Historical precedents */}
            {retrieve.prior_fitments.length > 0 && (
              <div>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                  Historical Precedents
                </p>
                <div className="flex flex-wrap gap-2">
                  {retrieve.prior_fitments.map((pf, i) => (
                    <span
                      key={i}
                      className="rounded border border-border bg-bg-raised px-2 py-0.5 text-[11px] text-text-secondary"
                    >
                      Wave {pf.wave} · {pf.country} · <Badge variant={pf.classification as Classification} className="ml-0.5" />
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* MS Learn refs */}
            {retrieve.ms_learn_refs.length > 0 && (
              <div>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                  Documentation
                </p>
                <div className="space-y-0.5">
                  {retrieve.ms_learn_refs.slice(0, 3).map((ref, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-xs text-text-secondary truncate flex-1">{ref.title}</span>
                      <span className="text-[11px] text-text-muted shrink-0">
                        {Math.round(ref.score * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Analysis trail accordion */}
        <button
          onClick={() => setTrailOpen((v) => !v)}
          className="flex w-full items-center gap-2 border-t border-border px-4 py-2.5 text-left text-xs font-medium text-text-secondary hover:text-text transition-colors"
        >
          {trailOpen ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0" />
          )}
          Analysis Trail
        </button>

        {trailOpen && (
          <div className="px-4 pb-4 space-y-3">
            {/* Composite score + route + LLM calls */}
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-text-muted">Composite score:</span>
                <span className="text-xs font-semibold text-text">
                  {Math.round(match.composite_score * 100)}%
                </span>
              </div>
              <span className="text-[11px] text-text-muted">
                {classify.llm_calls_used} LLM {classify.llm_calls_used === 1 ? 'call' : 'calls'}
              </span>
            </div>

            {/* 5-signal breakdown */}
            {match.signal_breakdown && (
              <div>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                  Signal Breakdown
                </p>
                <div className="space-y-1">
                  {Object.entries(match.signal_breakdown).map(([key, val]) => (
                    <div key={key} className="flex items-center gap-2">
                      <span className="w-40 shrink-0 text-[11px] text-text-secondary">
                        {SIGNAL_LABELS[key] ?? key}
                      </span>
                      <div className="h-1.5 flex-1 rounded-full bg-bg-raised">
                        <div
                          className="h-1.5 rounded-full bg-accent/50"
                          style={{ width: `${Math.round((val as number) * 100)}%` }}
                        />
                      </div>
                      <span className="w-10 text-right text-[11px] text-text-muted">
                        {Math.round((val as number) * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Anomaly flags */}
            {match.anomaly_flags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {match.anomaly_flags.map((flag) => (
                  <span
                    key={flag}
                    className="rounded-full border border-gap/30 bg-gap-muted px-2 py-0.5 text-[11px] text-gap-text"
                  >
                    {flag}
                  </span>
                ))}
              </div>
            )}

            {/* Quality metrics */}
            <div className="flex gap-4">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-text-muted">Specificity:</span>
                <span className="text-xs font-medium text-text">
                  {Math.round(ingest.specificity_score * 100)}%
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-text-muted">Completeness:</span>
                <span className="text-xs font-medium text-text">
                  {ingest.completeness_score}%
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
