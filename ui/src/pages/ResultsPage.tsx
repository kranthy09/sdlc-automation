import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { SummaryCards } from '@/components/results/SummaryCards'
import { DistributionChart } from '@/components/results/DistributionChart'
import { ResultsFilters } from '@/components/results/ResultsFilters'
import { ResultsTable } from '@/components/results/ResultsTable'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { useResults } from '@/hooks/useResults'
import { downloadReport } from '@/api/dynafit'
import { useUIStore } from '@/stores/uiStore'
import type { ResultsQuery } from '@/api/types'

export default function ResultsPage() {
  const { batchId } = useParams<{ batchId: string }>()
  const { addNotification } = useUIStore()
  const [query, setQuery] = useState<ResultsQuery>({
    sort: 'confidence',
    order: 'desc',
    page: 1,
    limit: 25,
  })
  const [downloading, setDownloading] = useState(false)

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
      addNotification({ type: 'error', message: 'Report download failed.' })
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Fitment Results"
        description={`Batch ${batchId}`}
        action={
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDownload}
            loading={downloading}
          >
            <Download className="h-3.5 w-3.5" />
            Download Excel
          </Button>
        }
      />

      <div className="space-y-4 px-6 pb-6">
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

        {/* Chart + filters row */}
        {data && (
          <div className="grid grid-cols-3 gap-4">
            <DistributionChart summary={data.summary} total={data.total} />
            <div className="col-span-2 flex flex-col justify-start gap-3">
              <p className="text-xs font-medium uppercase tracking-wide text-text-muted">Filters</p>
              <ResultsFilters
                query={query}
                summary={data.summary}
                onChange={setQuery}
              />
            </div>
          </div>
        )}

        {/* Results table */}
        {isLoading ? (
          <Skeleton className="h-96 rounded-xl" />
        ) : data ? (
          <ResultsTable
            results={data.results}
            total={data.total}
            query={query}
            loading={isFetching}
            onSort={handleSort}
            onPage={(page) => setQuery((q) => ({ ...q, page }))}
          />
        ) : null}
      </div>
    </div>
  )
}
