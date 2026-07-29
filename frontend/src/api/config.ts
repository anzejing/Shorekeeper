const BASE = '/api/config'

export interface ConfigItem {
  key: string
  label: string
  description: string
  type: 'string' | 'number' | 'boolean' | 'select' | 'array' | 'path'
  value: any
  default: any
  required: boolean
  secret: boolean
  group: string
  order: number
  options: any[]
}

export interface ConfigGroup {
  group: string
  order: number
  items: ConfigItem[]
}

export interface ConfigUpdateResponse {
  key: string
  value: any
  reload_required: boolean
}

export async function fetchConfig(): Promise<ConfigGroup[]> {
  const res = await fetch(BASE)
  if (!res.ok) throw new Error(`Failed to fetch config: ${res.status}`)
  return res.json()
}

export async function updateConfig(key: string, value: any): Promise<ConfigUpdateResponse> {
  const res = await fetch(`${BASE}/${key}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `Failed to update config: ${res.status}`)
  }
  return res.json()
}

export async function resetConfig(): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/reset`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to reset config: ${res.status}`)
  return res.json()
}
