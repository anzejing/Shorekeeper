const BASE = '/api/memory'

export interface MemoryEntry {
  memory_id: string
  content: string
  category: string
  source_session_id: string | null
  confidence: number
  created_at: string
  updated_at: string
}

export interface MemoryListResponse {
  memories: MemoryEntry[]
  total: number
}

export interface SearchResult {
  type: 'message' | 'memory'
  content: string
  session_id: string | null
  relevance_score: number
  created_at: string
}

export interface SearchResponse {
  results: SearchResult[]
  total: number
}

async function parseError(res: Response, fallback: string): Promise<Error> {
  const err = await res.json().catch(() => ({ detail: res.statusText }))
  return new Error(err.detail || fallback)
}

/** 获取长期记忆列表 */
export async function fetchMemories(
  category?: string,
  limit = 50,
  offset = 0,
): Promise<MemoryListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (category) params.set('category', category)
  const res = await fetch(`${BASE}/memories?${params}`)
  if (!res.ok) throw await parseError(res, `获取长期记忆失败: ${res.status}`)
  return res.json()
}

/** 更新长期记忆（内容/分类/置信度） */
export async function updateMemory(
  memoryId: string,
  body: { content?: string; category?: string; confidence?: number },
): Promise<MemoryEntry> {
  const res = await fetch(`${BASE}/memories/${encodeURIComponent(memoryId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res, `更新记忆失败: ${res.status}`)
  return res.json()
}

/** 删除长期记忆 */
export async function deleteMemory(memoryId: string): Promise<void> {
  const res = await fetch(`${BASE}/memories/${encodeURIComponent(memoryId)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw await parseError(res, `删除记忆失败: ${res.status}`)
}

/** 搜索消息和长期记忆 */
export async function searchMemory(
  query: string,
  searchType: 'all' | 'messages' | 'memories' = 'all',
  limit = 20,
): Promise<SearchResponse> {
  const res = await fetch(`${BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, search_type: searchType, limit }),
  })
  if (!res.ok) throw await parseError(res, `搜索失败: ${res.status}`)
  return res.json()
}
