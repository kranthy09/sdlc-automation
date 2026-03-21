import { create } from 'zustand'
import type {
  Classification,
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
  latencyTotalMs: number
}

interface ProgressState {
  batchId: string | null
  phases: PhaseState[]
  classifications: LiveClassificationRow[]
  reviewRequired: ReviewRequiredState | null
  complete: CompleteSummary | null
  error: string | null

  // Actions
  init: (batchId: string) => void
  dispatch: (msg: WSMessage) => void
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
  return phases.map((p) =>
    p.phase === msg.phase ? { ...p, status: 'active', phaseName: msg.phase_name } : p,
  )
}

function applyStepProgress(phases: PhaseState[], msg: WSStepProgress): PhaseState[] {
  return phases.map((p) =>
    p.phase === msg.phase
      ? { ...p, progressPct: msg.progress_pct, currentStep: `${msg.step} — ${msg.sub_step}` }
      : p,
  )
}

function applyPhaseComplete(phases: PhaseState[], msg: WSPhaseComplete): PhaseState[] {
  return phases.map((p) =>
    p.phase === msg.phase
      ? {
          ...p,
          status: 'complete',
          progressPct: 100,
          atomsProduced: msg.atoms_produced,
          atomsValidated: msg.atoms_validated,
          atomsFlagged: msg.atoms_flagged,
          latencyMs: msg.latency_ms,
        }
      : p,
  )
}

function applyClassification(
  rows: LiveClassificationRow[],
  msg: WSClassification,
): LiveClassificationRow[] {
  return [
    ...rows,
    {
      atomId: msg.atom_id,
      requirementText: msg.requirement_text,
      classification: msg.classification,
      confidence: msg.confidence,
      module: msg.module,
      rationale: msg.rationale,
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

  init: (batchId) =>
    set({
      batchId,
      phases: buildInitialPhases(),
      classifications: [],
      reviewRequired: null,
      complete: null,
      error: null,
    }),

  dispatch: (msg) =>
    set((state) => {
      switch (msg.type) {
        case 'phase_start':
          return { phases: applyPhaseStart(state.phases, msg) }

        case 'step_progress':
          return { phases: applyStepProgress(state.phases, msg) }

        case 'phase_complete':
          return { phases: applyPhaseComplete(state.phases, msg) }

        case 'classification':
          return { classifications: applyClassification(state.classifications, msg) }

        case 'review_required':
          return {
            reviewRequired: {
              reviewItems: msg.review_items,
              reasons: msg.reasons,
              reviewUrl: msg.review_url,
            },
          }

        case 'complete':
          return {
            complete: {
              total: msg.summary.total,
              fit: msg.summary.fit,
              partial_fit: msg.summary.partial_fit,
              gap: msg.summary.gap,
              reportUrl: msg.report_url,
              latencyTotalMs: msg.latency_total_ms,
            },
          }

        case 'error': {
          // Mark the active phase as errored
          const phases = state.phases.map((p) =>
            p.status === 'active' ? { ...p, status: 'error' as const } : p,
          )
          return { phases, error: msg.message }
        }

        default:
          return {}
      }
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
