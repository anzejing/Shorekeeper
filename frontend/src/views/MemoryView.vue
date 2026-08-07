<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useKunMessage, useKunAlert } from '@kungal/ui-vue'
import { useMemoryStore, MEMORY_CATEGORIES } from '../stores/memory'
import SessionMessagesDrawer from '../components/SessionMessagesDrawer.vue'
import MemoryEditDrawer from '../components/MemoryEditDrawer.vue'
import type { Session } from '../api/session'
import type { MemoryEntry } from '../api/memory'

const store = useMemoryStore()

onMounted(() => {
  store.loadSessions()
})

// 切换 Tab 时懒加载对应数据
watch(
  () => store.activeTab,
  (tab) => {
    if (tab === 'memories' && store.memories.length === 0) {
      store.loadMemories()
    }
  },
)

const tabs = [
  { value: 'history', textValue: '对话历史' },
  { value: 'memories', textValue: '长期记忆' },
]

const categoryOptions = [
  { value: null, label: '全部分类' },
  ...MEMORY_CATEGORIES.map((c) => ({ value: c.value, label: c.label })),
]

function categoryLabel(value: string): string {
  return MEMORY_CATEGORIES.find((c) => c.value === value)?.label || value
}

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

// 按当前 Tab 刷新对应数据
function handleRefresh() {
  if (store.activeTab === 'memories') store.loadMemories()
  else store.loadSessions()
}

async function handleSaveMemory(
  edits: { content: string; category: string; confidence: number },
) {
  if (!store.editingMemory) return
  store.savingMemory = true
  try {
    const updated = await store.saveMemoryEntry(store.editingMemory.memory_id, edits)
    store.editingMemory = updated
    useKunMessage('记忆已更新', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '保存失败', 'error')
  } finally {
    store.savingMemory = false
  }
}

async function handleDeleteMemory(m: MemoryEntry) {
  const ok = await useKunAlert({
    title: '删除记忆',
    message: '确定删除这条长期记忆？此操作不可恢复。',
  })
  if (!ok) return
  try {
    await store.removeMemory(m.memory_id)
    useKunMessage('记忆已删除', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '删除失败', 'error')
  }
}

function closeMemoryDrawer() {
  store.editingMemory = null
}
</script>

<template>
  <div class="max-w-3xl mx-auto overflow-y-auto p-6 w-full">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-xl font-bold">记忆管理</h2>
      <KunButton variant="flat" icon @click="handleRefresh">
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

    <!-- ─── 长期记忆 Tab ─── -->
    <KunTabPanel
      v-if="store.activeTab === 'memories'"
      value="memories"
      active="memories"
    >
      <!-- 分类筛选 -->
      <KunSelect
        v-model="store.memoryCategoryFilter"
        :options="categoryOptions"
        placeholder="全部分类"
        size="sm"
        class="w-40 mb-4"
      />

      <!-- Loading -->
      <div v-if="store.memoriesLoading" class="flex justify-center py-12">
        <KunLoading />
      </div>

      <!-- 列表 -->
      <template v-else>
        <div v-if="store.filteredMemories.length === 0" class="py-12">
          <KunNull description="暂无长期记忆" />
        </div>

        <div v-else class="flex flex-col gap-2">
          <KunCard
            v-for="m in store.filteredMemories"
            :key="m.memory_id"
            variant="flat"
            class="p-4"
            clickable
            is-hoverable
            @click="store.editingMemory = m"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 mb-1">
                  <KunChip size="xs" variant="flat" color="primary">
                    {{ categoryLabel(m.category) }}
                  </KunChip>
                  <span class="text-xs text-gray-400">
                    置信度 {{ Math.round(m.confidence * 100) }}%
                  </span>
                </div>
                <p class="text-sm text-gray-700 line-clamp-2 mb-1">
                  {{ m.content }}
                </p>
                <div class="text-xs text-gray-400">
                  {{ formatTime(m.updated_at) }}
                </div>
              </div>
              <div class="flex-shrink-0" @click.stop>
                <KunButton
                  size="xs"
                  variant="flat"
                  color="error"
                  is-icon-only
                  icon
                  @click="handleDeleteMemory(m)"
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

    <!-- 长期记忆编辑抽屉 -->
    <MemoryEditDrawer
      :memory="store.editingMemory"
      :saving="store.savingMemory"
      @close="closeMemoryDrawer"
      @save="handleSaveMemory"
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
