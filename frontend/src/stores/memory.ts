import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchSessions,
  fetchMessages,
  deleteSession,
  type Session,
  type Message,
} from '../api/session'
import {
  fetchMemories,
  updateMemory,
  deleteMemory,
  searchMemory,
  type MemoryEntry,
  type SearchResult,
} from '../api/memory'

// 长期记忆分类（与后端 MemoryCategory 一致）
export const MEMORY_CATEGORIES = [
  { value: 'preference', label: '偏好' },
  { value: 'fact', label: '事实' },
  { value: 'instruction', label: '指令' },
  { value: 'other', label: '其他' },
]

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

  // ─── 长期记忆 ───
  const memories = ref<MemoryEntry[]>([])
  const memoriesLoading = ref(false)
  const memoryCategoryFilter = ref<string | null>(null)

  // 编辑中的记忆
  const editingMemory = ref<MemoryEntry | null>(null)
  const savingMemory = ref(false)

  const filteredMemories = computed(() => {
    if (!memoryCategoryFilter.value) return memories.value
    return memories.value.filter(
      (m) => m.category === memoryCategoryFilter.value,
    )
  })

  /** 加载长期记忆列表 */
  async function loadMemories() {
    memoriesLoading.value = true
    error.value = null
    try {
      const res = await fetchMemories()
      memories.value = res.memories
    } catch (e: any) {
      error.value = e.message
    } finally {
      memoriesLoading.value = false
    }
  }

  /** 保存记忆编辑 */
  async function saveMemoryEntry(
    memoryId: string,
    edits: { content?: string; category?: string; confidence?: number },
  ): Promise<MemoryEntry> {
    const updated = await updateMemory(memoryId, edits)
    const idx = memories.value.findIndex((m) => m.memory_id === memoryId)
    if (idx !== -1) memories.value[idx] = updated
    return updated
  }

  /** 删除记忆 */
  async function removeMemory(memoryId: string) {
    await deleteMemory(memoryId)
    memories.value = memories.value.filter((m) => m.memory_id !== memoryId)
    if (editingMemory.value?.memory_id === memoryId) {
      editingMemory.value = null
    }
  }

  // ─── 搜索 ───
  const searchQuery = ref('')
  const searchResults = ref<SearchResult[]>([])
  const searching = ref(false)
  const searchError = ref<string | null>(null)

  /** 执行搜索（消息 + 长期记忆） */
  async function runSearch() {
    const q = searchQuery.value.trim()
    if (!q) return
    searching.value = true
    searchError.value = null
    try {
      const res = await searchMemory(q, 'all', 20)
      searchResults.value = res.results
    } catch (e: any) {
      searchError.value = e.message
    } finally {
      searching.value = false
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
    memories,
    memoriesLoading,
    memoryCategoryFilter,
    filteredMemories,
    editingMemory,
    savingMemory,
    loadMemories,
    saveMemoryEntry,
    removeMemory,
    searchQuery,
    searchResults,
    searching,
    searchError,
    runSearch,
  }
})
