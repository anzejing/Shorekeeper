const BASE = '/api/mcp'

export interface MCPServer {
  name: string
  transport: 'stdio' | 'streamable_http'
  enabled: boolean
  status: 'disconnected' | 'connecting' | 'connected' | 'error'
  tools_count: number
  error: string | null
  command: string
  url: string
}

export interface MCPListResponse {
  servers: MCPServer[]
  total: number
}

export interface AddMCPServerRequest {
  name: string
  transport?: 'stdio' | 'streamable_http'
  enabled?: boolean
  command?: string
  args?: string[]
  env?: Record<string, string> | null
  cwd?: string | null
  url?: string
  headers?: Record<string, string> | null
  timeout?: number
}

async function parseError(res: Response, fallback: string): Promise<Error> {
  const err = await res.json().catch(() => ({ detail: res.statusText }))
  return new Error(err.detail || fallback)
}

/** 获取 MCP 服务器列表 */
export async function fetchMCPServers(): Promise<MCPListResponse> {
  const res = await fetch(BASE)
  if (!res.ok) throw await parseError(res, '获取 MCP 服务器列表失败')
  return res.json()
}

/** 添加 MCP 服务器 */
export async function addMCPServer(
  request: AddMCPServerRequest,
): Promise<MCPServer> {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!res.ok) throw await parseError(res, '添加 MCP 服务器失败')
  return res.json()
}

/** 删除 MCP 服务器 */
export async function removeMCPServer(name: string): Promise<void> {
  const res = await fetch(`${BASE}/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw await parseError(res, '删除 MCP 服务器失败')
}

/** 重连 MCP 服务器 */
export async function reconnectMCPServer(name: string): Promise<MCPServer> {
  const res = await fetch(
    `${BASE}/${encodeURIComponent(name)}/reconnect`,
    { method: 'POST' },
  )
  if (!res.ok) throw await parseError(res, '重连 MCP 服务器失败')
  return res.json()
}
