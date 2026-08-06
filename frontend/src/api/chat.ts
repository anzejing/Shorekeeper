const BASE = '/api/chat'

export interface ChatStreamRequest {
  message: string
  session_id?: string
}

export interface ChatStreamResponse {
  run_id: string
  session_id: string
}

/** 流式对话：创建 Run 并立即返回 run_id */
export async function chatStream(
  request: ChatStreamRequest,
): Promise<ChatStreamResponse> {
  const res = await fetch(`${BASE}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `Chat stream failed: ${res.status}`)
  }
  return res.json()
}

export interface SSEEvent {
  event_id: string
  event_type: string
  run_id: string
  sequence: number
  timestamp: string
  delta?: string
  output?: any
  error_type?: string
  error_message?: string
  tool_name?: string
  [key: string]: any
}

/** 手动 SSE 连接（fetch + ReadableStream），完全控制生命周期 */
export async function connectSSE(
  runId: string,
  onEvent: (event: SSEEvent) => void,
  onDone: () => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/runs/${runId}/stream`, { signal })
  if (!res.ok || !res.body) {
    onDone()
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // 按 \n\n 分割 SSE 事件
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || '' // 最后一个可能是不完整的

      for (const part of parts) {
        if (!part.trim()) continue
        const event = parseSSEPart(part)
        if (event) {
          try {
            onEvent(event)
          } catch {
            // 忽略处理错误
          }
        }
      }
    }
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      console.error('[SSE] read error:', err)
    }
  } finally {
    reader.releaseLock()
    onDone()
  }
}

function parseSSEPart(raw: string): SSEEvent | null {
  // 事件类型由 data 中的 event_type 字段提供，忽略 SSE 的 event: 行
  let data = ''

  for (const line of raw.split('\n')) {
    if (line.startsWith('data: ')) {
      data = line.slice(6)
    }
  }

  if (!data) return null

  try {
    const parsed = JSON.parse(data)
    return parsed as SSEEvent
  } catch {
    return null
  }
}
