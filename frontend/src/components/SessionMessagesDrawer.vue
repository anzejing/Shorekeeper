<script setup lang="ts">
import { ref } from 'vue'
import type { Session, Message } from '../api/session'

defineProps<{
  session: Session | null
  messages: Message[]
  loading: boolean
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

// 长消息展开/收起
const expandedIds = ref<Set<string>>(new Set())

function toggleExpand(messageId: string) {
  const next = new Set(expandedIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  expandedIds.value = next
}

const ROLE_LABEL: Record<string, string> = {
  user: '用户',
  assistant: '助手',
  system: '系统',
  tool: '工具',
}

const ROLE_COLOR: Record<string, string> = {
  user: 'primary',
  assistant: 'success',
  system: 'warning',
  tool: 'default',
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function isLong(content: string): boolean {
  return content.length > 200
}
</script>

<template>
  <KunDrawer
    :model-value="!!session"
    placement="right"
    size="lg"
    :title="session ? `${session.title || '新对话'}（${session.message_count} 条消息）` : '会话消息'"
    :is-dismissable="true"
    :is-show-close-button="true"
    @update:model-value="(v: boolean) => !v && emit('close')"
  >
    <!-- 加载中 -->
    <div v-if="loading" class="flex justify-center py-12">
      <KunLoading />
    </div>

    <!-- 消息列表 -->
    <div v-else-if="messages.length" class="flex flex-col gap-2">
      <div
        v-for="msg in messages"
        :key="msg.message_id"
        class="msg-item"
      >
        <div class="msg-header">
          <KunChip
            size="xs"
            variant="flat"
            :color="(ROLE_COLOR[msg.role] as any) || 'default'"
          >
            {{ ROLE_LABEL[msg.role] || msg.role }}
          </KunChip>
          <span class="msg-time">{{ formatTime(msg.created_at) }}</span>
        </div>
        <p
          class="msg-content"
          :class="{ collapsed: isLong(msg.content) && !expandedIds.has(msg.message_id) }"
        >{{ msg.content }}</p>
        <button
          v-if="isLong(msg.content)"
          class="expand-btn"
          @click="toggleExpand(msg.message_id)"
        >
          {{ expandedIds.has(msg.message_id) ? '收起' : '展开全文' }}
        </button>
      </div>
    </div>

    <!-- 空状态 -->
    <KunNull v-else description="该会话暂无消息" />
  </KunDrawer>
</template>

<style scoped>
.msg-item {
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--kun-color-bg-hover, #f3f4f6);
}

.msg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.msg-time {
  font-size: 11px;
  color: var(--kun-color-text-secondary, #9ca3af);
}

.msg-content {
  font-size: 13px;
  line-height: 1.6;
  color: var(--kun-color-text, #374151);
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-content.collapsed {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.expand-btn {
  margin-top: 6px;
  font-size: 12px;
  color: var(--kun-color-primary, #3b82f6);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
}
</style>
