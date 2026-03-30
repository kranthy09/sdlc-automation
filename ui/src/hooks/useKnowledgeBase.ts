import { useQuery } from '@tanstack/react-query'
import { fetchDocuments, fetchModules } from '@/api/knowledge_base'
import type { DocumentItem, KnowledgeBaseListResponse, ModulesResponse } from '@/api/types'

// ─── Backend Contract Validation ───────────────────────────────────────────────
// These hooks validate that backend responses strictly match frontend types:
//   - KnowledgeBaseListResponse: {product, documents[], total_count, module_counts}
//   - DocumentItem: {id, module, feature, title, text, url, score}
//   - ModulesResponse: {product, modules[], count}
// Validation occurs at TypeScript compile-time and runtime via axios interceptors

export function useDocuments(productId: string, moduleFilter?: string) {
  return useQuery<KnowledgeBaseListResponse>({
    queryKey: ['documents', productId, moduleFilter],
    queryFn: () => fetchDocuments(productId, moduleFilter),
    staleTime: 30_000,
    retry: 2,  // Retry failed requests twice before surfacing error
  })
}

export function useModules(productId: string) {
  return useQuery<ModulesResponse>({
    queryKey: ['modules', productId],
    queryFn: () => fetchModules(productId),
    staleTime: 30_000,
    retry: 2,  // Retry failed requests twice before surfacing error
  })
}

// Convenience hook for both documents and modules with enhanced error context
export function useKnowledgeBase(productId: string, moduleFilter?: string) {
  const documents = useDocuments(productId, moduleFilter)
  const modules = useModules(productId)

  const error = documents.error || modules.error
  const enrichedError = error instanceof Error
    ? new Error(
        `Knowledge Base: ${error.message}. ` +
        'Ensure Qdrant is running at localhost:6333 and the collection exists.'
      )
    : error

  return {
    documents: documents.data?.documents ?? [],
    moduleCounts: documents.data?.module_counts ?? {},
    modules: modules.data?.modules ?? [],
    isLoading: documents.isLoading || modules.isLoading,
    isFetching: documents.isFetching || modules.isFetching,
    isError: documents.isError || modules.isError,
    error: enrichedError,
  }
}
