<script setup lang="ts">
import { onMounted } from 'vue'
import { useKunMessage, useKunAlert } from '@kungal/ui-vue'
import { useMemoryStore } from '../stores/memory'
import SessionMessagesDrawer from '../components/SessionMessagesDrawer.vue'
import type { Session } from '../api/session'

const store = useMemoryStore()

onMounted(() => {
  store.loadSessions()
})

const tabs = [{ value: 'history', textValue: '对话历史' }]

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    year: '2-digit',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function handleDeleteSession(session: Session) {
  const ok = await useKunAlert({
    title: '删除会话',
    message: `确定删除会话「${session.title || '新对话'}」？此操作不可恢复。`,
  })
  if (!ok) return
  try {
    await store.removeSession(session.session_id)
    useKunMessage('会话已删除', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '删除失败', 'error')
  }
}

function closeDrawer() {
  store.viewingSession = null
  store.messages = []
}
</script>

<template>
  <div class="max-w-3xl mx-auto overflow-y-auto p-6 w-full">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-xl font-bold">记忆管理</h2>
      <KunButton variant="flat" icon @click="store.loadSessions()">
        <template #icon>
          <KunIcon name="lucide:refresh-cw" />
        </template>
        <span>刷新</span>
      </KunButton>
    </div>

    <!-- Tab 切换 -->
    <KunTab
      v-model="store.activeTab"
      :items="tabs"
      variant="underlined"
      class="mb-4"
    />

    <!-- ─── 对话历史 Tab ─── -->
    <KunTabPanel
      v-if="store.activeTab === 'history'"
      value="history"
      active="history"
    >
      <!-- 搜索 -->
      <KunInput
        v-model="store.historyQuery"
        class="mb-4"
        placeholder="按标题或会话 ID 过滤..."
        size="sm"
      >
        <template #prefix>
          <KunIcon name="lucide:search" class="search-icon" />
        </template>
      </KunInput>

      <!-- Loading -->
      <div v-if="store.sessionsLoading" class="flex justify-center py-12">
        <KunLoading />
      </div>

      <!-- 错误 -->
      <KunInfo
        v-else-if="store.error"
        color="error"
        :description="store.error"
        class="mb-4"
      />

      <!-- 列表 -->
      <template v-else>
        <div v-if="store.filteredSessions.length === 0" class="py-12">
          <KunNull
            :description="store.historyQuery ? '没有匹配的会话' : '暂无会话记录'"
          />
        </div>

        <div v-else class="flex flex-col gap-2">
          <KunCard
            v-for="s in store.filteredSessions"
            :key="s.session_id"
            variant="flat"
            class="p-4"
            clickable
            is-hoverable
            @click="store.openSession(s)"
          >
            <div class="flex items-center justify-between gap-4">
              <div class="min-w-0 flex-1">
                <div class="font-semibold text-sm mb-1 truncate">
                  {{ s.title || '新对话' }}
                </div>
                <div class="flex items-center gap-2 text-xs text-gray-400">
                  <span>{{ formatTime(s.updated_at) }}</span>
                  <span>{{ s.message_count }} 条消息</span>
                </div>
              </div>
              <div class="flex-shrink-0 flex items-center gap-1" @click.stop>
                <KunButton
                  size="xs"
                  variant="flat"
                  color="error"
                  is-icon-only
                  icon
                  @click="handleDeleteSession(s)"
                >
                  <template #icon>
                    <KunIcon name="lucide:trash-2" />
                  </template>
                </KunButton>
              </div>
            </div>
          </KunCard>
        </div>
      </template>
    </KunTabPanel>

    <!-- 会话消息抽屉 -->
    <SessionMessagesDrawer
      :session="store.viewingSession"
      :messages="store.messages"
      :loading="store.messagesLoading"
      @close="closeDrawer"
    />
  </div>
</template>

<style scoped>
.search-icon {
  font-size: 14px;
  color: var(--kun-color-text-secondary, #9ca3af);
  flex-shrink: 0;
}
</style>
