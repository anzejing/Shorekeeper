const BASE = '/api/memory'

export interface Session {
  session_id: string
  title: string
  metadata: Record<string, any>
  created_at: string
  updated_at: string
  message_count: number
}

export interface SessionListResponse {
  sessions: Session[]
  total: number
}

export interface Message {
  message_id: string
  session_id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  metadata: Record<string, any>
  created_at: string
}

export interface MessageListResponse {
  messages: Message[]
  total: number
}

/** 获取会话列表 */
export async function fetchSessions(
  limit = 50,
  offset = 0,
): Promise<SessionListResponse> {
  const res = await fetch(`${BASE}/sessions?limit=${limit}&offset=${offset}`)
  if (!res.ok) throw new Error(`Failed to fetch sessions: ${res.status}`)
  return res.json()
}

/** 创建会话 */
export async function createSession(
  title = '',
): Promise<Session> {
  const res = await fetch(`${BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`)
  return res.json()
}

/** 获取会话详情 */
export async function getSession(sessionId: string): Promise<Session> {
  const res = await fetch(`${BASE}/sessions/${sessionId}`)
  if (!res.ok) throw new Error(`Failed to get session: ${res.status}`)
  return res.json()
}

/** 删除会话 */
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${BASE}/sessions/${sessionId}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(`Failed to delete session: ${res.status}`)
}

/** 获取会话消息 */
export async function fetchMessages(
  sessionId: string,
  limit = 50,
  offset = 0,
): Promise<MessageListResponse> {
  const res = await fetch(
    `${BASE}/sessions/${sessionId}/messages?limit=${limit}&offset=${offset}`,
  )
  if (!res.ok) throw new Error(`Failed to fetch messages: ${res.status}`)
  return res.json()
}
