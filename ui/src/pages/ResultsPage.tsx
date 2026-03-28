import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Download, FileSpreadsheet, LayoutList } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PageHeader } from '@/components/layout/PageHeader'
import { SummaryCards } from '@/components/results/SummaryCards'
import { ResultsFilters } from '@/components/results/ResultsFilters'
import { ResultsTable } from '@/components/results/ResultsTable'
import { ConfidenceHistogram } from '@/components/results/ConfidenceHistogram'
import { ModuleHeatmap } from '@/components/results/ModuleHeatmap'
import { ReportManifest } from '@/components/results/ReportManifest'
import { CountryRulesPanel } from '@/components/results/CountryRulesPanel'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorStateCard } from '@/components/ui/ErrorStateCard'
import { useResults } from '@/hooks/useResults'
import { downloadReport } from '@/api/dynafit'
import { useUIStore } from '@/stores/uiStore'
import type { ResultsQuery } from '@/api/types'
import { BarChart3 } from 'lucide-react'

type ChartView = 'histogram' | 'heatmap'

export default function ResultsPage() {
  const { batchId } = useParams<{ batchId: string }>()
  const navigate = useNavigate()
  const { addNotification } = useUIStore()
  const [query, setQuery] = useState<ResultsQuery>({
    sort: 'confidence',
    order: 'desc',
    page: 1,
    limit: 25,
  })
  const [downloading, setDownloading] = useState(false)
  const [chartView, setChartView] = useState<ChartView>('histogram')

  const { data, isLoading, isFetching } = useResults(batchId!, query)

  const handleSort = (field: string) => {
    setQuery((q) => ({
      ...q,
      sort: field,
      order: q.sort === field && q.order === 'desc' ? 'asc' : 'desc',
      page: 1,
    }))
  }

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const blob = await downloadReport(batchId!)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `fdd_report_${batchId}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      addNotification({ type: 'error', message: 'Report download failed. Use CSV export instead.' })
    } finally {
      setDownloading(false)
    }
  }

  const handleExportCsv = () => {
    if (!data?.results.length) return
    const headers = ['Req ID', 'Requirement', 'Module', 'Classification', 'Confidence', 'D365 Capability', 'D365 Navigation', 'Rationale', 'Config Steps', 'Gap Description', 'Gap Type', 'Dev Effort']
    const escape = (v: string) => `"${(v ?? '').replace(/"/g, '""')}"`
    const rows = data.results.map((r) => [
      r.atom_id, escape(r.requirement_text), r.module, r.classification,
      r.confidence, escape(r.d365_capability), escape(r.d365_navigation),
      escape(r.rationale), escape(r.config_steps ?? ''),
      escape(r.gap_description ?? ''), r.gap_type ?? '', r.dev_effort ?? '',
    ].join(','))
    const csv = [headers.join(','), ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `fdd_results_${batchId}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <PageHeader
        title="Fitment Results"
        description={`Batch ${batchId}`}
        action={
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
              <ArrowLeft className="h-3.5 w-3.5" />
              Back
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleDownload}
              loading={downloading}
            >
              <Download className="h-3.5 w-3.5" />
              Download Excel
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleExportCsv}
              disabled={!data?.results.length}
            >
              <FileSpreadsheet className="h-3.5 w-3.5" />
              Export CSV
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(`/features/${batchId}`)}
              disabled={!data?.results.length}
            >
              <LayoutList className="h-3.5 w-3.5" />
              Feature Report
            </Button>
          </div>
        }
      />

      <div className="space-y-4 px-6 pb-6">
        {/* Error state */}
        {!isLoading && !data && (
          <ErrorStateCard
            title="Failed to load results"
            message="Unable to fetch results for this batch. Please try again."
            onRetry={() => window.location.reload()}
          />
        )}

        {/* Summary cards */}
        {isLoading ? (
          <div className="grid grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        ) : data ? (
          <SummaryCards total={data.total} summary={data.summary} />
        ) : null}

        {/* Filters */}
        {data && (
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-text-muted">Filters</p>
            <ResultsFilters
              query={query}
              summary={data.summary}
              onChange={setQuery}
            />
          </div>
        )}

        {/* Charts */}
        {data && data.results.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-4">
              <p className="text-xs font-medium uppercase tracking-wide text-text-muted">Chart view:</p>
              <button
                onClick={() => setChartView('histogram')}
                className={cn(
                  'px-3 py-1.5 text-xs font-medium rounded transition-colors',
                  chartView === 'histogram'
                    ? 'bg-accent text-white'
                    : 'bg-bg-raised text-text-secondary hover:text-text-primary'
                )}
              >
                Confidence Distribution
              </button>
              <button
                onClick={() => setChartView('heatmap')}
                className={cn(
                  'px-3 py-1.5 text-xs font-medium rounded transition-colors',
                  chartView === 'heatmap'
                    ? 'bg-accent text-white'
                    : 'bg-bg-raised text-text-secondary hover:text-text-primary'
                )}
              >
                Module Heatmap
              </button>
            </div>
            <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-6">
              {chartView === 'histogram' ? (
                <ConfidenceHistogram results={data.results} />
              ) : (
                <ModuleHeatmap
                  summary={data.summary}
                  onModuleClick={(module) =>
                    setQuery((q) => ({
                      ...q,
                      module,
                      page: 1,
                    }))
                  }
                />
              )}
            </div>
          </div>
        )}

        {/* Results table */}
        {isLoading ? (
          <Skeleton className="h-96 rounded-xl" />
        ) : data ? (
          data.results.length > 0 ? (
            <ResultsTable
              batchId={batchId!}
              results={data.results}
              total={data.total}
              query={query}
              loading={isFetching}
              onSort={handleSort}
              onPage={(page) => setQuery((q) => ({ ...q, page }))}
            />
          ) : (
            <EmptyState
              icon={<BarChart3 className="h-12 w-12" />}
              title="No results found"
              description="Try adjusting your filters to find matching requirements."
              action={{
                label: 'Reset filters',
                onClick: () => setQuery({ sort: 'confidence', order: 'desc', page: 1, limit: 25 }),
              }}
            />
          )
        ) : null}

        {/* Report downloads */}
        {data && (
          <ReportManifest batchId={batchId!} onDownload={handleDownload} />
        )}

        {/* Country rules */}
        {data && data.results.length > 0 && (
          <CountryRulesPanel country={data.results[0]?.country || 'US'} />
        )}
      </div>
    </div>
  )
}
