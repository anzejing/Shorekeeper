<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  disabled?: boolean
  canStop?: boolean
}>()

const emit = defineEmits<{
  send: [content: string]
  stop: []
}>()

const inputText = ref('')

function handleSend() {
  const text = inputText.value.trim()
  if (!text || props.disabled) return
  emit('send', text)
  inputText.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="chat-input-wrapper">
    <div class="chat-input-box">
      <textarea
        v-model="inputText"
        class="chat-textarea"
        placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
        rows="1"
        :disabled="disabled"
        @keydown="handleKeydown"
      />
      <KunButton
        v-if="canStop"
        class="stop-btn"
        color="danger"
        icon
        is-icon-only
        title="停止生成"
        @click="emit('stop')"
      >
        <template #icon>
          <KunIcon name="lucide:square" />
        </template>
      </KunButton>
      <KunButton
        v-else
        class="send-btn"
        color="primary"
        icon
        is-icon-only
        :disabled="disabled || !inputText.trim()"
        @click="handleSend"
      >
        <template #icon>
          <KunIcon name="lucide:send" />
        </template>
      </KunButton>
    </div>
    <div class="input-hint">
      AI 可能会犯错，请核实重要信息。
    </div>
  </div>
</template>

<style scoped>
.chat-input-wrapper {
  padding: 12px 24px 16px;
  flex-shrink: 0;
}

.chat-input-box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  border: 1px solid var(--kun-color-border, #d1d5db);
  border-radius: 12px;
  padding: 8px 12px;
  background: var(--kun-color-bg, #ffffff);
  transition: border-color 0.15s;
}

.chat-input-box:focus-within {
  border-color: var(--kun-color-primary, #3b82f6);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.chat-textarea {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  font-size: 14px;
  line-height: 1.5;
  max-height: 120px;
  min-height: 24px;
  font-family: inherit;
  color: var(--kun-color-text, #1f2937);
  background: transparent;
}

.chat-textarea::placeholder {
  color: var(--kun-color-text-secondary, #9ca3af);
}

.send-btn, .stop-btn {
  width: 36px;
  height: 36px;
  padding: 0;
  border-radius: 50%;
  flex-shrink: 0;
  font-size: 16px;
}

.input-hint {
  font-size: 12px;
  color: var(--kun-color-text-secondary, #9ca3af);
  text-align: center;
  padding-top: 6px;
}
</style>
