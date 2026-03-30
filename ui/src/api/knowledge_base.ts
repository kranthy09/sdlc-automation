import { apiClient } from './client'
import type {
  KnowledgeBaseListResponse,
  ModulesResponse,
} from './types'

// ─── Knowledge Base API functions ──────────────────────────────────────────────
//
// Backend Contract (api/routes/knowledge_base.py):
//   GET /{product_id}/knowledge-base/docs
//     → Returns: KnowledgeBaseListResponse
//       - product: string
//       - documents: DocumentItem[] (id, module, feature, title, text, url, score)
//       - total_count: number
//       - module_counts: Record<string, number>
//
//   GET /{product_id}/knowledge-base/modules
//     → Returns: { product, modules: string[], count: number }
//
// Frontend expects exact type match via @tanstack/react-query
// Stale time: 30s (fresh knowledge base monitoring without server overload)

export async function fetchDocuments(
  productId: string,
  moduleFilter?: string,
): Promise<KnowledgeBaseListResponse> {
  const params: Record<string, string> = {}
  if (moduleFilter) {
    params.module = moduleFilter
  }

  const res = await apiClient.get<KnowledgeBaseListResponse>(
    `/${productId}/knowledge-base/docs`,
    { params },
  )
  return res.data
}

export async function fetchModules(productId: string): Promise<ModulesResponse> {
  const res = await apiClient.get<ModulesResponse>(`/${productId}/knowledge-base/modules`)
  return res.data
}
