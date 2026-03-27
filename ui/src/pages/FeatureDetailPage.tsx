import { useState, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Search } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { useBatchJourney } from '@/hooks/useBatchJourney'
import { useResults } from '@/hooks/useResults'
import { FeatureReportCard } from '@/components/features/FeatureReportCard'
import type { Classification } from '@/api/types'

type Tab = 'ALL' | Classification

const TABS: { key: Tab; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'FIT', label: 'Fit' },
  { key: 'PARTIAL_FIT', label: 'Partial Fit' },
  { key: 'GAP', label: 'Gap' },
]

export default function FeatureDetailPage() {
  const { batchId } = useParams<{ batchId: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<Tab>('ALL')
  const [moduleFilter, setModuleFilter] = useState<string>('ALL')
  const [search, setSearch] = useState('')

  const { data: journeyData, isLoading } = useBatchJourney(batchId!)
  const { data: resultsData } = useResults(batchId!, { limit: 1 })

  const modules = useMemo(() => {
    if (!journeyData?.atoms) return []
    return Array.from(new Set(journeyData.atoms.map((a) => a.ingest.module))).sort()
  }, [journeyData])

  const filtered = useMemo(() => {
    if (!journeyData?.atoms) return []
    return journeyData.atoms
      .filter((a) => activeTab === 'ALL' || a.output.classification === activeTab)
      .filter((a) => moduleFilter === 'ALL' || a.ingest.module === moduleFilter)
      .filter((a) => !search || a.ingest.requirement_text.toLowerCase().includes(search.toLowerCase()))
      .sort((a, b) => b.output.confidence - a.output.confidence)
  }, [journeyData, activeTab, moduleFilter, search])

  const summary = resultsData?.summary

  return (
    <div>
      <PageHeader
        title="Feature Report"
        description={`Batch ${batchId}`}
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Button>
        }
      />

      <div className="space-y-4 px-6 pb-6">
        {/* Summary strip */}
        {summary && (
          <div className="flex gap-6 rounded-xl border border-border bg-surface px-5 py-3">
            <Stat label="TOTAL" value={summary.fit + summary.partial_fit + summary.gap} />
            <div className="w-px bg-border" />
            <Stat label="FIT" value={summary.fit} color="text-fit-text" />
            <Stat label="PARTIAL FIT" value={summary.partial_fit} color="text-partial-text" />
            <Stat label="GAP" value={summary.gap} color="text-gap-text" />
          </div>
        )}

        {/* Tabs + Filters */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Classification tabs */}
          <div className="flex gap-1 rounded-lg border border-border bg-surface p-0.5">
            {TABS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  activeTab === key
                    ? 'bg-accent text-white'
                    : 'text-text-muted hover:text-text'
                }`}
              >
                {label}
                {journeyData && (
                  <span className="ml-1.5 text-[10px] opacity-70">
                    {key === 'ALL'
                      ? journeyData.atoms.length
                      : journeyData.atoms.filter((a) => a.output.classification === key).length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Module filter */}
          <select
            value={moduleFilter}
            onChange={(e) => setModuleFilter(e.target.value)}
            className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs text-text focus:outline-none"
          >
            <option value="ALL">All modules</option>
            {modules.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>

          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              placeholder="Search requirements..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface py-1.5 pl-8 pr-3 text-xs text-text placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        </div>

        {/* Cards */}
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-40 rounded-xl" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-border bg-surface p-12 text-center text-sm text-text-muted">
            No requirements match the current filters.
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((journey, i) => (
              <FeatureReportCard key={journey.atom_id} journey={journey} index={i + 1} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-medium uppercase tracking-wider text-text-muted">{label}</span>
      <span className={`text-lg font-bold ${color ?? 'text-text'}`}>{value}</span>
    </div>
  )
}
