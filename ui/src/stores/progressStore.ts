import { create } from 'zustand'
import type {
  AtomJourney,
  Classification,
  ProgressResponse,
  ResultsResponse,
  ReviewResponse,
  WSClassification,
  WSMessage,
  WSPhaseComplete,
  WSPhaseStart,
  WSStepProgress,
} from '@/api/types'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PhaseState {
  phase: number
  phaseName: string
  status: 'pending' | 'active' | 'complete' | 'error'
  progressPct: number
  currentStep: string | null
  atomsProduced: number
  atomsValidated: number
  atomsFlagged: number
  latencyMs: number | null
}

export interface LiveClassificationRow {
  atomId: string
  requirementText: string
  classification: Classification
  confidence: number
  module: string
  rationale: string
  d365Capability: string
  d365Navigation: string
  journey: AtomJourney | null
}

interface ReviewRequiredState {
  reviewItems: number
  reasons: { low_confidence: number; conflicts: number; anomalies: number }
  reviewUrl: string
}

interface CompleteSummary {
  total: number
  fit: number
  partial_fit: number
  gap: number
  reportUrl: string
  resultsUrl: string
  latencyTotalMs: number
}

interface ProgressState {
  batchId: string | null
  phases: PhaseState[]
  classifications: LiveClassificationRow[]
  reviewRequired: ReviewRequiredState | null
  complete: CompleteSummary | null
  error: string | null
  activeGate: 1 | 2 | 3 | 4 | null

  // Actions
  init: (batchId: string) => void
  dispatch: (msg: WSMessage) => void
  hydrate: (resultsData: ResultsResponse, reviewData?: ReviewResponse | null) => void
  hydrateFromProgress: (data: ProgressResponse) => void
  reset: () => void
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const PHASE_NAMES = ['Ingestion', 'RAG', 'Matching', 'Classification', 'Validation']

function buildInitialPhases(): PhaseState[] {
  return PHASE_NAMES.map((name, i) => ({
    phase: i + 1,
    phaseName: name,
    status: 'pending',
    progressPct: 0,
    currentStep: null,
    atomsProduced: 0,
    atomsValidated: 0,
    atomsFlagged: 0,
    latencyMs: null,
  }))
}

function applyPhaseStart(phases: PhaseState[], msg: WSPhaseStart): PhaseState[] {
  // Pipeline is strictly sequential: if phase N starts, all phases < N must be complete.
  // Mark any prior phase still showing as 'active' or 'pending' as 'complete' —
  // their phase_complete events may have been missed during a WebSocket reconnect.
  return phases.map((p) => {
    if (p.phase === msg.phase) {
      return { ...p, status: 'active', phaseName: msg.phase_name }
    }
    if (p.phase < msg.phase && p.status !== 'complete') {
      return { ...p, status: 'complete', progressPct: 100 }
    }
    return p
  })
}

function applyStepProgress(phases: PhaseState[], msg: WSStepProgress): PhaseState[] {
  const pct = msg.total > 0 ? Math.round((msg.completed / msg.total) * 100) : 0
  return phases.map((p) =>
    p.phase === msg.phase
      ? { ...p, progressPct: pct, currentStep: msg.step }
      : p,
  )
}

function applyPhaseComplete(phases: PhaseState[], msg: WSPhaseComplete): PhaseState[] {
  return phases.map((p) => {
    if (p.phase === msg.phase) {
      return {
        ...p,
        status: 'complete',
        progressPct: 100,
        atomsProduced: msg.atoms_produced,
        atomsValidated: msg.atoms_validated,
        atomsFlagged: msg.atoms_flagged,
        latencyMs: msg.latency_ms,
      }
    }
    // Same sequential guarantee: if phase N completes, prior phases must be done
    if (p.phase < msg.phase && p.status !== 'complete') {
      return { ...p, status: 'complete', progressPct: 100 }
    }
    return p
  })
}

function applyClassification(
  rows: LiveClassificationRow[],
  msg: WSClassification,
): LiveClassificationRow[] {
  if (rows.some((r) => r.atomId === msg.atom_id)) return rows
  return [
    ...rows,
    {
      atomId: msg.atom_id,
      requirementText: msg.requirement_text ?? '',
      classification: msg.classification as Classification,
      confidence: msg.confidence,
      module: msg.module ?? '',
      rationale: msg.rationale ?? '',
      d365Capability: msg.d365_capability ?? '',
      d365Navigation: msg.d365_navigation ?? '',
      journey: msg.journey ?? null,
    },
  ]
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useProgressStore = create<ProgressState>((set) => ({
  batchId: null,
  phases: buildInitialPhases(),
  classifications: [],
  reviewRequired: null,
  complete: null,
  error: null,
  activeGate: null,

  init: (batchId) =>
    set({
      batchId,
      phases: buildInitialPhases(),
      classifications: [],
      reviewRequired: null,
      complete: null,
      error: null,
      activeGate: null,
    }),

  dispatch: (msg) =>
    set((state) => {
      switch (msg.event) {
        case 'phase_start':
          return { phases: applyPhaseStart(state.phases, msg), activeGate: null }

        case 'step_progress':
          return { phases: applyStepProgress(state.phases, msg) }

        case 'phase_complete':
          return { phases: applyPhaseComplete(state.phases, msg) }

        case 'phase_gate':
          return { activeGate: msg.gate }

        case 'classification':
          return { classifications: applyClassification(state.classifications, msg) }

        case 'review_required':
          return {
            reviewRequired: {
              reviewItems: msg.review_items,
              reasons: {
                low_confidence: msg.reasons.low_confidence,
                conflicts: msg.reasons.conflicts ?? 0,
                anomalies: msg.reasons.anomalies ?? 0,
              },
              reviewUrl: msg.review_url,
            },
          }

        case 'complete':
          return {
            complete: {
              total: msg.total,
              fit: msg.fit_count,
              partial_fit: msg.partial_fit_count,
              gap: msg.gap_count,
              reportUrl: msg.report_url ?? '',
              resultsUrl: msg.results_url ?? '',
              latencyTotalMs: 0,
            },
          }

        case 'error': {
          const phases = state.phases.map((p) =>
            p.status === 'active' ? { ...p, status: 'error' as const } : p,
          )
          return { phases, error: msg.message }
        }

        default:
          return {}
      }
    }),

  hydrate: (resultsData, reviewData) =>
    set((state) => {
      if (resultsData.status === 'complete') {
        const phases = state.phases.map((p) => ({
          ...p,
          status: 'complete' as const,
          progressPct: 100,
        }))
        const classifications = resultsData.results.map((r) => ({
          atomId: r.atom_id,
          requirementText: r.requirement_text,
          classification: r.classification,
          confidence: r.confidence,
          module: r.module,
          rationale: r.rationale,
          d365Capability: r.d365_capability,
          d365Navigation: r.d365_navigation,
          journey: r.journey ?? null,
        }))
        const { fit, partial_fit, gap } = resultsData.summary
        return {
          phases,
          classifications,
          complete: {
            total: fit + partial_fit + gap,
            fit,
            partial_fit,
            gap,
            reportUrl: '',
            resultsUrl: '',
            latencyTotalMs: 0,
          },
        }
      }
      if (resultsData.status === 'review_required') {
        const reviewItems = reviewData?.items.length ?? 0
        // summary.total includes REVIEW_REQUIRED atoms; fit+partial_fit+gap alone
        // would be 0 when all atoms are flagged, causing negative atomsValidated.
        const total = resultsData.summary.total ?? (resultsData.summary.fit + resultsData.summary.partial_fit + resultsData.summary.gap)
        const phases = state.phases.map((p) => {
          if (p.phase < 5) {
            // Phase 4 gets the classification stats; phases 1-3 just marked complete
            if (p.phase === 4) {
              return {
                ...p,
                status: 'complete' as const,
                progressPct: 100,
                atomsProduced: total,
                atomsValidated: Math.max(0, total - reviewItems),
                atomsFlagged: reviewItems,
              }
            }
            return { ...p, status: 'complete' as const, progressPct: 100 }
          }
          return p
        })
        return {
          phases,
          reviewRequired: {
            reviewItems,
            reasons: { low_confidence: reviewItems, conflicts: 0, anomalies: 0 },
            reviewUrl: `/review/${resultsData.batch_id}`,
          },
        }
      }
      return {}
    }),

  hydrateFromProgress: (data) =>
    set((state) => {
      const phases = state.phases.map((p) => {
        const match = data.phases.find((dp) => dp.phase === p.phase)
        if (!match || match.status === 'pending') return p
        return {
          ...p,
          status: match.status as PhaseState['status'],
          phaseName: match.phase_name,
          currentStep: match.current_step,
          progressPct: match.progress_pct,
          atomsProduced: match.atoms_produced,
          atomsValidated: match.atoms_validated,
          atomsFlagged: match.atoms_flagged,
          latencyMs: match.latency_ms,
        }
      })

      // Merge persisted classifications (don't lose WS ones)
      let classifications = state.classifications
      if (data.classifications?.length) {
        const existing = new Set(classifications.map((c) => c.atomId))
        const newRows: LiveClassificationRow[] = data.classifications
          .filter((c) => !existing.has(c.atom_id))
          .map((c) => ({
            atomId: c.atom_id,
            requirementText: c.requirement_text ?? '',
            classification: c.classification,
            confidence: c.confidence,
            module: c.module ?? '',
            rationale: c.rationale ?? '',
            d365Capability: c.d365_capability ?? '',
            d365Navigation: c.d365_navigation ?? '',
            journey: c.journey ?? null,
          }))
        if (newRows.length > 0) {
          classifications = [...classifications, ...newRows]
        }
      }

      // Check if batch is at a gate
      let activeGate: 1 | 2 | 3 | 4 | null = null
      if (data.status?.startsWith('gate_')) {
        try {
          activeGate = parseInt(data.status.split('_')[1]) as 1 | 2 | 3 | 4
        } catch {
          activeGate = null
        }
      }

      return { phases, classifications, activeGate }
    }),

  reset: () =>
    set({
      batchId: null,
      phases: buildInitialPhases(),
      classifications: [],
      reviewRequired: null,
      complete: null,
      error: null,
    }),
}))
