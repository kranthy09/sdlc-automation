import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, RotateCcw } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { ComparisonSelector } from '@/components/compare/ComparisonSelector'
import { ComparisonSummary } from '@/components/compare/ComparisonSummary'
import { ComparisonTable } from '@/components/compare/ComparisonTable'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { useComparison } from '@/hooks/useComparison'
import { BarChart3 } from 'lucide-react'

export default function ComparePage() {
  const navigate = useNavigate()
  const [batchId1, setBatchId1] = useState<string>('')
  const [batchId2, setBatchId2] = useState<string>('')
  const { data1, data2, comparison, isLoading } = useComparison({ batchId1, batchId2 })

  const canCompare = batchId1 && batchId2 && batchId1 !== batchId2

  const handleSwap = () => {
    const temp = batchId1
    setBatchId1(batchId2)
    setBatchId2(temp)
  }

  const handleReset = () => {
    setBatchId1('')
    setBatchId2('')
  }

  return (
    <div>
      <PageHeader
        title="Batch Comparison"
        description="Analyze differences between two completed batches"
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate('/dashboard')}>
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Button>
        }
      />

      <div className="space-y-4 px-6 pb-6 max-w-6xl">
        {/* Selector section */}
        <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-5">
          <p className="mb-4 text-xs font-medium text-text-muted uppercase tracking-wide">
            Select batches to compare
          </p>
          <div className="grid grid-cols-[1fr_auto_1fr] gap-4 items-end">
            <ComparisonSelector
              label="First Batch"
              value={batchId1}
              onChange={setBatchId1}
              excludeId={batchId2}
            />

            <button
              onClick={handleSwap}
              disabled={!canCompare}
              className="p-2 rounded-lg border border-bg-border hover:bg-bg-raised transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Swap batches"
            >
              <RotateCcw className="h-4 w-4 text-text-muted" />
            </button>

            <ComparisonSelector
              label="Second Batch"
              value={batchId2}
              onChange={setBatchId2}
              excludeId={batchId1}
            />
          </div>

          {canCompare && (
            <div className="mt-4 flex justify-end">
              <Button variant="ghost" size="sm" onClick={handleReset}>
                Reset
              </Button>
            </div>
          )}
        </div>

        {/* Results section */}
        {!canCompare ? (
          <EmptyState
            icon={<BarChart3 className="h-12 w-12" />}
            title="Select two batches"
            description="Choose two different completed batches to compare their fitment results and classifications."
          />
        ) : isLoading ? (
          <div className="space-y-4">
            <Skeleton className="h-32 rounded-xl" />
            <Skeleton className="h-96 rounded-xl" />
          </div>
        ) : comparison ? (
          <>
            {/* Summary metrics */}
            <div>
              <p className="mb-3 text-xs font-medium text-text-muted uppercase tracking-wide">
                Comparison Summary
              </p>
              <ComparisonSummary batch1={comparison.batch1} batch2={comparison.batch2} />
            </div>

            {/* Changes table */}
            <div>
              <p className="mb-3 text-xs font-medium text-text-muted uppercase tracking-wide">
                Classification Changes
              </p>
              <ComparisonTable
                results1={comparison.batch1.results}
                results2={comparison.batch2.results}
              />
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}
