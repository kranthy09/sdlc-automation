import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { Classification } from '@/api/types'

// ─── Tailwind class merger ────────────────────────────────────────────────────
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

// ─── Classification helpers ───────────────────────────────────────────────────
export const CLASSIFICATION_LABEL: Record<Classification, string> = {
  FIT: 'Fit',
  PARTIAL_FIT: 'Partial Fit',
  GAP: 'Gap',
}

export const CLASSIFICATION_COLOR: Record<Classification, string> = {
  FIT: 'text-fit-text bg-fit-muted border-fit',
  PARTIAL_FIT: 'text-partial-text bg-partial-muted border-partial',
  GAP: 'text-gap-text bg-gap-muted border-gap',
}

// ─── Confidence formatting ────────────────────────────────────────────────────
export function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function confidenceTier(value: number): 'high' | 'medium' | 'low' {
  if (value >= 0.85) return 'high'
  if (value >= 0.6) return 'medium'
  return 'low'
}

export const CONFIDENCE_TIER_COLOR: Record<'high' | 'medium' | 'low', string> = {
  high: 'text-fit-text',
  medium: 'text-partial-text',
  low: 'text-gap-text',
}

// ─── Date formatting ──────────────────────────────────────────────────────────
export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(iso))
}

export function formatDuration(ms: number): string {
  if (ms < 1_000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1_000).toFixed(1)}s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1_000)}s`
}

// ─── File size ────────────────────────────────────────────────────────────────
export function formatBytes(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`
  return `${(bytes / 1_048_576).toFixed(1)} MB`
}
