import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchSessions,
  fetchMessages,
  deleteSession,
  type Session,
  type Message,
} from '../api/session'

export const useMemoryStore = defineStore('memory', () => {
  // ─── 当前 Tab ───
  const activeTab = ref<string>('history')

  // ─── 对话历史 ───
  const sessions = ref<Session[]>([])
  const sessionsLoading = ref(false)
  const error = ref<string | null>(null)
  const historyQuery = ref('')

  // 展开查看的会话
  const viewingSession = ref<Session | null>(null)
  const messages = ref<Message[]>([])
  const messagesLoading = ref(false)

  // 标题关键词过滤
  const filteredSessions = computed(() => {
    const q = historyQuery.value.trim().toLowerCase()
    if (!q) return sessions.value
    return sessions.value.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.session_id.toLowerCase().includes(q),
    )
  })

  /** 加载会话列表 */
  async function loadSessions() {
    sessionsLoading.value = true
    error.value = null
    try {
      const res = await fetchSessions(100, 0)
      sessions.value = res.sessions
    } catch (e: any) {
      error.value = e.message
    } finally {
      sessionsLoading.value = false
    }
  }

  /** 打开会话，加载其消息 */
  async function openSession(session: Session) {
    viewingSession.value = session
    messages.value = []
    messagesLoading.value = true
    try {
      const res = await fetchMessages(session.session_id, 100, 0)
      messages.value = res.messages
    } catch (e: any) {
      error.value = e.message
    } finally {
      messagesLoading.value = false
    }
  }

  /** 删除会话（后端删除 + 本地移除） */
  async function removeSession(sessionId: string) {
    await deleteSession(sessionId)
    sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
    if (viewingSession.value?.session_id === sessionId) {
      viewingSession.value = null
      messages.value = []
    }
  }

  return {
    activeTab,
    sessions,
    sessionsLoading,
    error,
    historyQuery,
    filteredSessions,
    viewingSession,
    messages,
    messagesLoading,
    loadSessions,
    openSession,
    removeSession,
  }
})
