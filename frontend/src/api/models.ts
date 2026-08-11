const BASE = '/api/models'

// ─── 类型 ─────────────────────────────────────────────────

export type ProviderKind = 'openai' | 'openai_like' | 'anthropic' | 'gemini'

export interface ModelProvider {
  provider_id: string
  name: string
  kind: ProviderKind
  base_url: string
  api_key: string
  enabled: boolean
  source: 'catalog' | 'custom'
  created_at: string
  updated_at: string
}

export interface ModelEntry {
  provider_id: string
  model_id: string
  display_name: string
  litellm_name: string
  enabled: boolean
  meta_source: 'models_dev' | 'provider_api' | 'custom'
  metadata: Record<string, any>
}

export interface CurrentModel {
  provider_id: string
  model_id: string
  litellm_name: string
  display_name: string
}

export interface CatalogProvider {
  provider_id: string
  name: string
  kind: ProviderKind
  api: string
  model_count: number
  doc: string
}

export interface CatalogStatus {
  synced_at: string
  data_date: string
  etag: string
  provider_count: number
  model_count: number
  has_cache: boolean
}

export interface TestResult {
  ok: boolean
  latency_ms: number
  model: string
}

// ─── 请求辅助 ────────────────────────────────────────────

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `请求失败: ${res.status}`)
  }
  return res.json() as Promise<T>
}

// ─── Provider ────────────────────────────────────────────

export function fetchProviders(): Promise<ModelProvider[]> {
  return request(`${BASE}/providers`)
}

export function createProvider(body: Partial<ModelProvider> & {
  import_models?: boolean
}): Promise<ModelProvider> {
  return request(`${BASE}/providers`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateProvider(
  providerId: string,
  body: Partial<ModelProvider>,
): Promise<ModelProvider> {
  return request(`${BASE}/providers/${providerId}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function deleteProvider(providerId: string): Promise<{ message: string }> {
  return request(`${BASE}/providers/${providerId}`, { method: 'DELETE' })
}

// ─── 模型 ────────────────────────────────────────────────

export function fetchModels(providerId: string): Promise<ModelEntry[]> {
  return request(`${BASE}/providers/${providerId}/models`)
}

export function addModel(
  providerId: string,
  modelId: string,
): Promise<ModelEntry> {
  return request(`${BASE}/providers/${providerId}/models`, {
    method: 'POST',
    body: JSON.stringify({ model_id: modelId }),
  })
}

export function removeModel(
  providerId: string,
  modelId: string,
): Promise<{ message: string }> {
  return request(`${BASE}/providers/${providerId}/models/${modelId}`, {
    method: 'DELETE',
  })
}

export function syncProviderModels(
  providerId: string,
): Promise<{ provider_id: string; count: number }> {
  return request(`${BASE}/providers/${providerId}/sync`, { method: 'POST' })
}

export function testConnection(
  providerId: string,
  modelId: string,
): Promise<TestResult> {
  return request(`${BASE}/providers/${providerId}/test`, {
    method: 'POST',
    body: JSON.stringify({ model_id: modelId }),
  })
}

// ─── models.dev 目录 ─────────────────────────────────────

export function fetchCatalogStatus(): Promise<CatalogStatus> {
  return request(`${BASE}/catalog/status`)
}

export function syncCatalog(): Promise<{
  status: 'updated' | 'unchanged'
  data_date: string
  provider_count?: number
  model_count?: number
}> {
  return request(`${BASE}/catalog/sync`, { method: 'POST' })
}

export function fetchCatalogProviders(search = ''): Promise<CatalogProvider[]> {
  return request(`${BASE}/catalog/providers?search=${encodeURIComponent(search)}`)
}

export function fetchCatalogModels(
  providerId: string,
): Promise<Record<string, any>> {
  return request(`${BASE}/catalog/providers/${providerId}/models`)
}

// ─── 全局当前模型 ────────────────────────────────────────

export function fetchCurrent(): Promise<CurrentModel | null> {
  return request(`${BASE}/current`)
}

export function setCurrent(
  providerId: string,
  modelId: string,
): Promise<CurrentModel> {
  return request(`${BASE}/current`, {
    method: 'PUT',
    body: JSON.stringify({ provider_id: providerId, model_id: modelId }),
  })
}

export function clearCurrent(): Promise<{ message: string }> {
  return request(`${BASE}/current`, { method: 'DELETE' })
}
