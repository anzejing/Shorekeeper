import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chatStream, connectSSE, type SSEEvent } from '../api/chat'
import {
  fetchSessions,
  fetchMessages,
  deleteSession,
  type Session,
} from '../api/session'
import { resolveApproval, resumeRun, cancelRun } from '../api/approval'

// --- 消息块类型 ---

export interface TextBlock {
  type: 'text'
  content: string
}

export interface ThinkingBlock {
  type: 'thinking'
  content: string
}

export interface ToolCallBlock {
  type: 'tool_call'
  toolName: string
  status: 'running' | 'success' | 'error'
  output?: string
  durationMs?: number
  startTime?: number
}

export interface ApprovalBlock {
  type: 'approval'
  toolName: string
  toolArguments: Record<string, any>
  approvalId?: string
  reason?: string
  status: 'pending' | 'approved' | 'denied'
}

export type MessageBlock = TextBlock | ThinkingBlock | ToolCallBlock | ApprovalBlock

/** 对话中的展示消息 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  blocks?: MessageBlock[]
  thinking?: string
  streaming?: boolean
  created_at?: string
}

export const useChatStore = defineStore('chat', () => {
  // --- 会话列表 ---
  const sessions = ref<Session[]>([])
  const sessionsLoading = ref(false)

  // --- 当前会话 ---
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const messagesLoading = ref(false)

  // --- 发送状态 ---
  const sending = ref(false)
  const streamingContent = ref('')
  const error = ref<string | null>(null)

  // --- 当前 Run ---
  const currentRunId = ref<string | null>(null)

  // --- SSE 连接 ---
  let _abortController: AbortController | null = null
  const _processedSequences = new Set<number>()
  let _sseConnectionId = 0
  let _resuming = false

  // --- 计算属性 ---
  const currentSession = computed(() =>
    sessions.value.find((s) => s.session_id === currentSessionId.value) ?? null,
  )

  const canStop = computed(() => sending.value && currentRunId.value !== null)

  // --- 会话列表操作 ---

  async function loadSessions() {
    sessionsLoading.value = true
    try {
      const res = await fetchSessions()
      sessions.value = res.sessions
    } catch (e: any) {
      error.value = e.message
    } finally {
      sessionsLoading.value = false
    }
  }

  async function removeSession(sessionId: string) {
    try {
      await deleteSession(sessionId)
      sessions.value = sessions.value.filter(
        (s) => s.session_id !== sessionId,
      )
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = null
        messages.value = []
      }
    } catch (e: any) {
      error.value = e.message
    }
  }

  // --- 会话切换 ---

  async function switchSession(sessionId: string) {
    if (currentSessionId.value === sessionId) return

    disconnectSSE()
    currentSessionId.value = sessionId
    currentRunId.value = null
    messages.value = []
    messagesLoading.value = true

    try {
      const res = await fetchMessages(sessionId)
      messages.value = res.messages.map((m) => ({
        id: m.message_id,
        role: m.role as ChatMessage['role'],
        content: m.content,
        created_at: m.created_at,
      }))
    } catch (e: any) {
      error.value = e.message
    } finally {
      messagesLoading.value = false
    }
  }

  // --- 发送消息 ---

  async function sendMessage(content: string) {
    if (!content.trim() || sending.value) return

    error.value = null
    sending.value = true
    streamingContent.value = ''
    _processedSequences.clear()
    _resuming = false

    const userMsg: ChatMessage = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content,
    }
    messages.value.push(userMsg)

    const assistantMsgId = `temp-assistant-${Date.now()}`
    const assistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      blocks: [],
      streaming: true,
    }
    messages.value.push(assistantMsg)

    try {
      const { run_id, session_id } = await chatStream({
        message: content,
        session_id: currentSessionId.value ?? undefined,
      })

      currentRunId.value = run_id

      if (!currentSessionId.value) {
        currentSessionId.value = session_id
      }

      await loadSessions()

      _connectSSE(run_id, assistantMsgId)
    } catch (e: any) {
      error.value = e.message
      const idx = messages.value.findIndex((m) => m.id === assistantMsgId)
      if (idx !== -1) messages.value.splice(idx, 1)
      sending.value = false
    }
  }

  // --- SSE 连接 ---

  function _connectSSE(runId: string, assistantMsgId: string) {
    disconnectSSE()
    // 记录连接 id：旧连接被 abort 后其 onDone 不应再影响状态
    const connId = ++_sseConnectionId
    _abortController = new AbortController()

    connectSSE(
      runId,
      (event: SSEEvent) => handleSSEEvent(event, assistantMsgId),
      () => {
        // 已不是当前连接（重连/切换会话后）→ 忽略
        if (connId !== _sseConnectionId) return
        // 流结束 — 清理状态
        const idx = messages.value.findIndex((m) => m.id === assistantMsgId)
        if (idx === -1) return
        const msg = messages.value[idx]
        // 如果还在流式（没被事件处理结束），finalize
        if (msg.streaming) {
          finalizeAssistantMessage(idx)
        }
      },
      _abortController.signal,
    )
  }

  // --- SSE 事件处理 ---

  function handleSSEEvent(event: SSEEvent, assistantMsgId: string) {
    // 跳过已处理的事件（SSE 重连时会重放历史事件）
    if (event.sequence !== undefined && _processedSequences.has(event.sequence)) {
      return
    }
    if (event.sequence !== undefined) {
      _processedSequences.add(event.sequence)
    }

    const idx = messages.value.findIndex((m) => m.id === assistantMsgId)
    if (idx === -1) return
    const msg = messages.value[idx]

    switch (event.event_type) {
      case 'model_text_delta':
        if (event.delta) {
          messages.value[idx] = { ...msg, content: msg.content + event.delta }
          streamingContent.value = messages.value[idx].content
        }
        break

      case 'model_reasoning_delta':
        if (event.delta) {
          messages.value[idx] = {
            ...msg,
            thinking: (msg.thinking || '') + event.delta,
          }
        }
        break

      case 'tool_execution_started':
        _addToolCallBlock(idx, {
          type: 'tool_call',
          toolName: event.tool_name || 'unknown',
          status: 'running',
          startTime: Date.now(),
        })
        break

      case 'tool_execution_completed':
        _updateLastToolCall(idx, {
          status: 'success',
          durationMs: event.duration_ms || undefined,
        })
        break

      case 'tool_execution_failed':
        _updateLastToolCall(idx, {
          status: 'error',
          output: event.error_message || '执行失败',
        })
        break

      case 'tool_approval_requested':
        _handleApprovalRequested(idx, event)
        break

      case 'run_suspended':
        _handleSuspension(idx, event)
        break

      case 'run_completed':
        finalizeAssistantMessage(idx)
        break

      case 'run_failed':
        finalizeAssistantMessage(idx)
        error.value = event.error_message || 'Run 执行失败'
        break
    }
  }

  function _addToolCallBlock(msgIdx: number, block: ToolCallBlock) {
    const msg = messages.value[msgIdx]
    const blocks = [...(msg.blocks || []), block]
    messages.value[msgIdx] = { ...msg, blocks }
  }

  function _updateLastToolCall(msgIdx: number, update: Partial<ToolCallBlock>) {
    const msg = messages.value[msgIdx]
    const blocks = [...(msg.blocks || [])]
    for (let i = blocks.length - 1; i >= 0; i--) {
      if (blocks[i].type === 'tool_call') {
        blocks[i] = { ...blocks[i], ...update } as ToolCallBlock
        break
      }
    }
    messages.value[msgIdx] = { ...msg, blocks }
  }

  function _handleSuspension(msgIdx: number, _event: SSEEvent) {
    // 停止流式状态，等待 tool_approval_requested 事件
    const msg = messages.value[msgIdx]
    messages.value[msgIdx] = { ...msg, streaming: false }
    sending.value = false
    streamingContent.value = ''
  }

  function _handleApprovalRequested(msgIdx: number, event: SSEEvent) {
    // 添加审批块（包含 approval_id）
    const approvalBlock: ApprovalBlock = {
      type: 'approval',
      toolName: event.tool_name || 'unknown',
      toolArguments: event.arguments || {},
      approvalId: event.approval_id,
      reason: event.reason,
      status: 'pending',
    }
    _addToolCallBlock(msgIdx, approvalBlock as any)
  }

  // --- 审批操作 ---

  async function _resolveAndResume(
    assistantMsgId: string,
    approvalBlockIdx: number,
    approved: boolean,
  ) {
    if (_resuming) return // 防止重复调用
    _resuming = true

    const msgIdx = messages.value.findIndex((m) => m.id === assistantMsgId)
    if (msgIdx === -1) { _resuming = false; return }

    const msg = messages.value[msgIdx]
    const blocks = [...(msg.blocks || [])]
    const block = blocks[approvalBlockIdx] as ApprovalBlock
    if (!block || block.type !== 'approval') { _resuming = false; return }

    // 更新 UI 状态
    blocks[approvalBlockIdx] = { ...block, status: approved ? 'approved' : 'denied' }
    messages.value[msgIdx] = { ...msg, blocks, streaming: true }
    sending.value = true

    try {
      // 1. 解决审批
      if (block.approvalId) {
        await resolveApproval(block.approvalId, approved)
      }

      // 2. 恢复 Run
      if (currentRunId.value) {
        const idempotencyKey = `${approved ? 'approve' : 'deny'}-${Date.now()}`
        await resumeRun(currentRunId.value, approved, idempotencyKey)

        // 3. 重新连接 SSE。
        // 注意：不清理 _processedSequences — 后端 stream 会从 sequence 0 重放历史事件，
        // 依赖 _processedSequences 去重，避免重复添加审批块 / 重复追加文本。
        _connectSSE(currentRunId.value, assistantMsgId)
      }
    } catch (e: any) {
      error.value = e.message
      sending.value = false
      messages.value[msgIdx] = { ...messages.value[msgIdx], streaming: false }
    } finally {
      _resuming = false
    }
  }

  function approveTool(assistantMsgId: string, approvalBlockIdx: number) {
    _resolveAndResume(assistantMsgId, approvalBlockIdx, true)
  }

  function denyTool(assistantMsgId: string, approvalBlockIdx: number) {
    _resolveAndResume(assistantMsgId, approvalBlockIdx, false)
  }

  // --- 停止生成 ---

  async function stopGeneration() {
    if (!currentRunId.value) return
    try {
      await cancelRun(currentRunId.value, '用户取消')
    } catch {
      // 忽略
    }
    sending.value = false
    streamingContent.value = ''
    disconnectSSE()
  }

  // --- 重新生成 ---

  async function regenerate(messageIndex: number) {
    // 找到这条 assistant 消息之前的 user 消息
    let userContent = ''
    for (let i = messageIndex - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') {
        userContent = messages.value[i].content
        break
      }
    }
    if (!userContent) return

    // 移除当前 assistant 消息
    messages.value.splice(messageIndex, 1)

    // 重新发送
    await sendMessage(userContent)
  }

  // --- 消息完成 ---

  function finalizeAssistantMessage(msgIndex: number) {
    const msg = messages.value[msgIndex]
    if (msg) {
      messages.value[msgIndex] = { ...msg, streaming: false }
    }
    sending.value = false
    streamingContent.value = ''
    currentRunId.value = null
    // 不断开 SSE — stream 会自然结束，onDone 回调处理
  }

  function disconnectSSE() {
    if (_abortController) {
      _abortController.abort()
      _abortController = null
    }
  }

  // --- 新建会话 ---

  function newSession() {
    disconnectSSE()
    currentSessionId.value = null
    currentRunId.value = null
    messages.value = []
    sending.value = false
    streamingContent.value = ''
    error.value = null
  }

  return {
    sessions,
    sessionsLoading,
    currentSessionId,
    currentSession,
    currentRunId,
    messages,
    messagesLoading,
    sending,
    streamingContent,
    error,
    canStop,
    loadSessions,
    removeSession,
    switchSession,
    sendMessage,
    newSession,
    approveTool,
    denyTool,
    stopGeneration,
    regenerate,
  }
})
