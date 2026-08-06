<script setup lang="ts">
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '../stores/chat'
import ChatMessageList from '../components/ChatMessageList.vue'
import ChatInput from '../components/ChatInput.vue'

const chat = useChatStore()
const route = useRoute()
const router = useRouter()

// URL 是会话状态的唯一来源：
// /chat → 新会话；/chat/{sessionId} → 指定会话（刷新保持）
watch(
  () => route.params.sessionId,
  async (sessionId) => {
    const ok = await chat.loadSession(
      typeof sessionId === 'string' ? sessionId : null,
    )
    // 会话不存在/已删除 → URL 回退新会话
    if (!ok && route.path !== '/chat') {
      router.replace('/chat')
    }
  },
  { immediate: true },
)

async function handleSend(content: string) {
  const sessionId = await chat.sendMessage(content)
  // 新会话首次发送：URL 带上 session_id（replace，避免历史堆栈膨胀）
  if (sessionId && route.params.sessionId !== sessionId) {
    router.replace(`/chat/${sessionId}`)
  }
}

function handleStop() {
  chat.stopGeneration()
}

function handleApprove(msgIndex: number, blockIndex: number) {
  const msg = chat.messages[msgIndex]
  chat.approveTool(msg.id, blockIndex)
}

function handleDeny(msgIndex: number, blockIndex: number) {
  const msg = chat.messages[msgIndex]
  chat.denyTool(msg.id, blockIndex)
}

function handleRegenerate(msgIndex: number) {
  chat.regenerate(msgIndex)
}
</script>

<template>
  <div class="chat-view">
    <!-- 消息列表 -->
    <ChatMessageList
      :messages="chat.messages"
      :loading="chat.messagesLoading"
      @approve="handleApprove"
      @deny="handleDeny"
      @regenerate="handleRegenerate"
    />

    <!-- 错误提示 -->
    <div v-if="chat.error" class="chat-error">
      <KunIcon name="lucide:alert-circle" />
      <span>{{ chat.error }}</span>
      <button class="error-dismiss" @click="chat.error = null">
        <KunIcon name="lucide:x" />
      </button>
    </div>

    <!-- 输入框 -->
    <ChatInput
      :disabled="chat.sending"
      :can-stop="chat.canStop"
      @send="handleSend"
      @stop="handleStop"
    />
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}

.chat-error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 24px;
  padding: 8px 12px;
  background: var(--kun-color-error-light, #fef2f2);
  color: var(--kun-color-error, #ef4444);
  border-radius: 8px;
  font-size: 13px;
}

.error-dismiss {
  margin-left: auto;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--kun-color-error, #ef4444);
  padding: 2px;
}
</style>
