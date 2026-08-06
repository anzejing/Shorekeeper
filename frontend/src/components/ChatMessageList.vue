<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import ChatMessage from './ChatMessage.vue'
import type { ChatMessage as ChatMessageType } from '../stores/chat'

const props = defineProps<{
  messages: ChatMessageType[]
  loading?: boolean
}>()

const emit = defineEmits<{
  approve: [msgIndex: number, blockIndex: number]
  deny: [msgIndex: number, blockIndex: number]
  regenerate: [msgIndex: number]
}>()

const listRef = ref<HTMLElement | null>(null)

watch(
  () => props.messages.length,
  () => scrollToBottom(),
)

watch(
  () => props.messages.map((m) => m.content + (m.thinking || '')).join(''),
  () => scrollToBottom(),
)

// 块内容变化时也滚动（工具执行状态变化等）
watch(
  () => JSON.stringify(props.messages.map((m) => m.blocks)),
  () => scrollToBottom(),
)

async function scrollToBottom() {
  await nextTick()
  if (listRef.value) {
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
}
</script>

<template>
  <div ref="listRef" class="message-list">
    <div v-if="loading" class="message-loading">
      <KunLoading />
    </div>

    <div v-else-if="messages.length === 0" class="message-empty">
      <KunIcon name="lucide:message-square" class="empty-icon" />
      <p>开始一个新的对话</p>
    </div>

    <ChatMessage
      v-for="(msg, mi) in messages"
      :key="msg.id"
      :message="msg"
      :message-index="mi"
      @approve="(bi) => emit('approve', mi, bi)"
      @deny="(bi) => emit('deny', mi, bi)"
      @regenerate="emit('regenerate', mi)"
    />
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
}

.message-loading {
  display: flex;
  justify-content: center;
  padding: 48px 0;
}

.message-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--kun-color-text-secondary, #9ca3af);
  gap: 12px;
}

.empty-icon {
  font-size: 48px;
  opacity: 0.3;
}

.message-empty p {
  font-size: 15px;
}
</style>
