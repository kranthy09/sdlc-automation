import { useMemo, useState } from 'react'
import { BookOpenIcon, ChevronLeft, ChevronRight } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DocumentCard } from '@/components/knowledge-base/DocumentCard'
import { DocumentDetailModal } from '@/components/knowledge-base/DocumentDetailModal'
import { KBSearchBar } from '@/components/knowledge-base/KBSearchBar'
import { ModuleFilter } from '@/components/knowledge-base/ModuleFilter'
import { ErrorStateCard } from '@/components/ui/ErrorStateCard'
import { EmptyState } from '@/components/ui/EmptyState'
import { Skeleton } from '@/components/ui/Skeleton'
import { useKnowledgeBase } from '@/hooks/useKnowledgeBase'
import type { DocumentItem } from '@/api/types'

const PRODUCT_ID = 'd365_fo'
const ITEMS_PER_PAGE = 12

export default function KnowledgeBasePage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedModule, setSelectedModule] = useState<string | null>(null)
  const [selectedDocument, setSelectedDocument] = useState<DocumentItem | null>(null)
  const [currentPage, setCurrentPage] = useState(1)

  const { documents, moduleCounts, modules, isLoading, isError, error } = useKnowledgeBase(
    PRODUCT_ID,
    selectedModule ?? undefined,
  )

  // Filter documents by search query
  const filteredDocuments = useMemo(() => {
    if (!searchQuery.trim()) return documents

    const query = searchQuery.toLowerCase()
    return documents.filter(
      (doc) =>
        doc.title.toLowerCase().includes(query) ||
        doc.feature.toLowerCase().includes(query) ||
        doc.text.toLowerCase().includes(query) ||
        doc.module.toLowerCase().includes(query),
    )
  }, [documents, searchQuery])

  // Paginate documents
  const totalPages = Math.ceil(filteredDocuments.length / ITEMS_PER_PAGE)
  const startIndex = (currentPage - 1) * ITEMS_PER_PAGE
  const paginatedDocuments = filteredDocuments.slice(startIndex, startIndex + ITEMS_PER_PAGE)

  // Reset to page 1 when search/filter changes
  const handleSearchChange = (value: string) => {
    setSearchQuery(value)
    setCurrentPage(1)
  }

  const handleModuleSelect = (module: string | null) => {
    setSelectedModule(module)
    setCurrentPage(1)
  }

  return (
    <div>
      <PageHeader
        title="Knowledge Base"
        description="Reference library of MS Learn documentation across D365 F&O modules"
      />

      <div className="space-y-6 px-6 pb-6">
        {/* Search Bar */}
        <section aria-label="Search documents">
          <KBSearchBar value={searchQuery} onChange={handleSearchChange} />
        </section>

        {/* Module Filter */}
        {!isError && (
          <section aria-label="Filter by module">
            <div className="flex flex-wrap gap-2">
              <p className="text-xs font-medium text-text-muted uppercase tracking-wide self-center">
                Filter by module:
              </p>
              <ModuleFilter
                modules={modules}
                moduleCounts={moduleCounts}
                selectedModule={selectedModule}
                onModuleSelect={handleModuleSelect}
              />
            </div>
          </section>
        )}

        {/* Loading State */}
        {isLoading && (
          <div aria-live="polite" aria-label="Loading documents">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="rounded-xl border border-bg-border bg-bg-surface p-4 space-y-3">
                  <Skeleton className="h-6 w-24" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-4/5" />
                  <Skeleton className="h-16 w-full" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Error State */}
        {isError && (
          <div aria-live="assertive">
            <ErrorStateCard
              title="Failed to load knowledge base"
              message={
                error instanceof Error
                  ? error.message
                  : 'An error occurred while loading documents. The knowledge base service may be temporarily unavailable.'
              }
              onRetry={() => window.location.reload()}
            />
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !isError && filteredDocuments.length === 0 && (
          <div role="status" aria-live="polite">
            <EmptyState
              icon={<BookOpenIcon className="h-12 w-12" />}
              title={searchQuery ? 'No documents found' : 'No documents available'}
              description={
                searchQuery
                  ? `Try adjusting your search query or select a different module`
                  : 'The knowledge base is currently empty'
              }
            />
          </div>
        )}

        {/* Document Grid */}
        {!isLoading && !isError && filteredDocuments.length > 0 && (
          <section aria-label="Knowledge base documents">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {paginatedDocuments.map((doc) => (
                <DocumentCard
                  key={doc.id}
                  document={doc}
                  onClick={() => setSelectedDocument(doc)}
                />
              ))}
            </div>
          </section>
        )}

        {/* Pagination and Results count */}
        {!isLoading && !isError && filteredDocuments.length > 0 && (
          <div className="space-y-4">
            {/* Results count */}
            <div className="text-center">
              <p className="text-xs text-text-muted">
                Showing {startIndex + 1}–{Math.min(startIndex + ITEMS_PER_PAGE, filteredDocuments.length)} of {filteredDocuments.length} documents
              </p>
            </div>

            {/* Pagination controls */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2">
                <button
                  onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                  aria-label="Previous page"
                  className="p-2 rounded-lg border border-bg-border text-text-secondary hover:text-text-primary hover:border-accent/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>

                <div className="flex items-center gap-1">
                  {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                    <button
                      key={page}
                      onClick={() => setCurrentPage(page)}
                      aria-label={`Go to page ${page}`}
                      aria-current={page === currentPage ? 'page' : undefined}
                      className={`h-8 w-8 rounded border text-xs font-medium transition-colors ${
                        page === currentPage
                          ? 'bg-accent text-white border-accent'
                          : 'border-bg-border text-text-secondary hover:text-text-primary hover:border-accent/50'
                      }`}
                    >
                      {page}
                    </button>
                  ))}
                </div>

                <button
                  onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                  aria-label="Next page"
                  className="p-2 rounded-lg border border-bg-border text-text-secondary hover:text-text-primary hover:border-accent/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Detail Modal */}
      <DocumentDetailModal
        document={selectedDocument}
        onClose={() => setSelectedDocument(null)}
      />
    </div>
  )
}
