<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { onMounted, ref, computed } from 'vue'
import { useKunAlert } from '@kungal/ui-vue'
import { useChatStore } from '../stores/chat'
import type { Session } from '../api/session'

const route = useRoute()
const router = useRouter()
const chat = useChatStore()

const navItems = [
  { path: '/skills', label: 'Skills', icon: 'lucide:puzzle' },
  { path: '/memory', label: '记忆', icon: 'lucide:brain' },
  { path: '/config', label: '配置', icon: 'lucide:settings' },
]

const searchQuery = ref('')

onMounted(() => {
  chat.loadSessions()
})

// 会话分组
interface SessionGroup {
  label: string
  sessions: Session[]
}

const groupedSessions = computed<SessionGroup[]>(() => {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today.getTime() - 86400000)
  const weekAgo = new Date(today.getTime() - 7 * 86400000)

  const filtered = searchQuery.value
    ? chat.sessions.filter((s) =>
        s.title.toLowerCase().includes(searchQuery.value.toLowerCase()),
      )
    : chat.sessions

  const groups: SessionGroup[] = [
    { label: '今天', sessions: [] },
    { label: '昨天', sessions: [] },
    { label: '本周', sessions: [] },
    { label: '更早', sessions: [] },
  ]

  for (const s of filtered) {
    const d = new Date(s.updated_at)
    if (d >= today) groups[0].sessions.push(s)
    else if (d >= yesterday) groups[1].sessions.push(s)
    else if (d >= weekAgo) groups[2].sessions.push(s)
    else groups[3].sessions.push(s)
  }

  return groups.filter((g) => g.sessions.length > 0)
})

function handleNewChat() {
  chat.newSession()
  if (route.path !== '/chat') {
    router.push('/chat')
  }
}

function handleSelectSession(sessionId: string) {
  chat.switchSession(sessionId)
  if (route.path !== '/chat') {
    router.push('/chat')
  }
}

async function handleDeleteSession(e: Event, sessionId: string) {
  e.stopPropagation()
  const ok = await useKunAlert({
    title: '删除会话',
    message: '确定删除这个会话？此操作不可恢复。',
  })
  if (ok) {
    chat.removeSession(sessionId)
  }
}
</script>

<template>
  <aside class="sidebar">
    <!-- 上部：导航 -->
    <div class="sidebar-nav">
      <h1 class="sidebar-title">
        <img src="/favicon-32x32.png" alt="Shorekeeper" class="sidebar-logo" />
        <span>Shorekeeper</span>
      </h1>
      <button class="new-chat-btn" @click="handleNewChat">
        <KunIcon name="lucide:plus" />
        <span>新对话</span>
      </button>
      <nav class="nav-list">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: route.path === item.path }"
        >
          <KunIcon :name="item.icon" class="nav-icon" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
    </div>

    <!-- 下部：会话列表 -->
    <div class="session-list-wrapper">
      <div class="session-list-header">
        <span>会话历史</span>
      </div>

      <!-- 搜索框 -->
      <div class="session-search">
        <KunIcon name="lucide:search" class="search-icon" />
        <input
          v-model="searchQuery"
          class="search-input"
          placeholder="搜索会话..."
        />
      </div>

      <div class="session-list">
        <div v-if="chat.sessionsLoading" class="session-loading">
          <KunLoading />
        </div>

        <template v-else>
          <div v-for="group in groupedSessions" :key="group.label" class="session-group">
            <div class="group-label">{{ group.label }}</div>
            <div
              v-for="session in group.sessions"
              :key="session.session_id"
              class="session-item"
              :class="{ active: chat.currentSessionId === session.session_id }"
              @click="handleSelectSession(session.session_id)"
            >
              <span class="session-title">{{ session.title || '新对话' }}</span>
              <button
                class="session-delete"
                title="删除会话"
                @click="handleDeleteSession($event, session.session_id)"
              >
                <KunIcon name="lucide:trash-2" />
              </button>
            </div>
          </div>

          <div
            v-if="groupedSessions.length === 0"
            class="session-empty"
          >
            {{ searchQuery ? '无匹配会话' : '暂无会话' }}
          </div>
        </template>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 260px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--kun-color-border, #e5e7eb);
  background: var(--kun-color-bg-elevated, #f9fafb);
}

.sidebar-nav {
  padding: 16px 12px 8px;
  flex-shrink: 0;
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 700;
  padding: 0 8px 12px;
  color: var(--kun-color-text, #111827);
}

.sidebar-logo {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  flex-shrink: 0;
}

.new-chat-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--kun-color-border, #d1d5db);
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  color: var(--kun-color-text, #374151);
  transition: background 0.15s;
}

.new-chat-btn:hover {
  background: var(--kun-color-bg-hover, #f3f4f6);
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  text-decoration: none;
  font-size: 14px;
  color: var(--kun-color-text-secondary, #6b7280);
  transition: all 0.15s;
}

.nav-item:hover {
  background: var(--kun-color-bg-hover, #f3f4f6);
  color: var(--kun-color-text, #111827);
}

.nav-item.active {
  background: var(--kun-color-primary-light, #eff6ff);
  color: var(--kun-color-primary, #3b82f6);
  font-weight: 500;
}

.nav-icon {
  font-size: 18px;
  flex-shrink: 0;
}

/* 会话列表 */
.session-list-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 0 12px 12px;
}

.session-list-header {
  font-size: 12px;
  font-weight: 600;
  color: var(--kun-color-text-secondary, #9ca3af);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 8px 8px 4px;
  flex-shrink: 0;
}

/* 搜索 */
.session-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  margin: 0 0 4px;
  border: 1px solid var(--kun-color-border, #e5e7eb);
  border-radius: 6px;
  background: var(--kun-color-bg, #fff);
}

.search-icon {
  font-size: 14px;
  color: var(--kun-color-text-secondary, #9ca3af);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 12px;
  background: transparent;
  color: var(--kun-color-text, #374151);
}

.search-input::placeholder {
  color: var(--kun-color-text-secondary, #9ca3af);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.session-loading {
  display: flex;
  justify-content: center;
  padding: 16px 0;
}

.session-group {
  margin-bottom: 4px;
}

.group-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--kun-color-text-secondary, #9ca3af);
  padding: 6px 8px 2px;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.session-item:hover {
  background: var(--kun-color-bg-hover, #f3f4f6);
}

.session-item.active {
  background: var(--kun-color-primary-light, #eff6ff);
}

.session-title {
  flex: 1;
  font-size: 13px;
  color: var(--kun-color-text, #374151);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-item.active .session-title {
  color: var(--kun-color-primary, #3b82f6);
  font-weight: 500;
}

.session-delete {
  opacity: 0;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  color: var(--kun-color-text-secondary, #9ca3af);
  border-radius: 4px;
  transition: all 0.15s;
  flex-shrink: 0;
}

.session-item:hover .session-delete {
  opacity: 1;
}

.session-delete:hover {
  color: var(--kun-color-error, #ef4444);
  background: var(--kun-color-error-light, #fef2f2);
}

.session-empty {
  font-size: 13px;
  color: var(--kun-color-text-secondary, #9ca3af);
  text-align: center;
  padding: 16px 8px;
}
</style>
