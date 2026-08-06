<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import type { ChatMessage, MessageBlock, ApprovalBlock } from '../stores/chat'
import ToolCallCard from './ToolCallCard.vue'
import ApprovalCard from './ApprovalCard.vue'

const props = defineProps<{
  message: ChatMessage
  messageIndex: number
}>()

const emit = defineEmits<{
  approve: [blockIndex: number]
  deny: [blockIndex: number]
  regenerate: []
}>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  return md.render(props.message.content)
})

// 代码块复制按钮
const contentRef = ref<HTMLElement | null>(null)

function addCopyButtons() {
  if (!contentRef.value) return
  const pres = contentRef.value.querySelectorAll('pre')
  pres.forEach((pre) => {
    if (pre.querySelector('.copy-btn')) return
    pre.style.position = 'relative'
    const btn = document.createElement('button')
    btn.className = 'copy-btn'
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>'
    btn.title = '复制'
    btn.onclick = async () => {
      const code = pre.querySelector('code')
      if (code) {
        await navigator.clipboard.writeText(code.textContent || '')
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>'
        setTimeout(() => {
          btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>'
        }, 2000)
      }
    }
    pre.appendChild(btn)
  })
}

watch(() => renderedContent.value, () => nextTick(addCopyButtons))

const renderedThinking = computed(() => {
  if (!props.message.thinking) return ''
  return md.render(props.message.thinking)
})

const isUser = computed(() => props.message.role === 'user')
const isStreaming = computed(() => props.message.streaming)
const blocks = computed(() => props.message.blocks || [])

const showRegenerate = computed(() => {
  return (
    !isUser.value &&
    !isStreaming.value &&
    props.message.role === 'assistant'
  )
})

function getApprovalBlock(block: MessageBlock): ApprovalBlock {
  return block as unknown as ApprovalBlock
}
</script>

<template>
  <div class="chat-message" :class="{ user: isUser, assistant: !isUser }">
    <div class="message-avatar">
      <KunIcon :name="isUser ? 'lucide:user' : 'lucide:bot'" />
    </div>
    <div class="message-body">
      <div class="message-role">{{ isUser ? '你' : 'AI' }}</div>

      <!-- 用户消息 -->
      <div v-if="isUser" class="message-content user-content">
        {{ message.content }}
      </div>

      <!-- AI 消息 -->
      <template v-else>
        <!-- 思考内容 -->
        <details v-if="message.thinking" class="thinking-block">
          <summary class="thinking-header">
            <KunIcon name="lucide:brain" class="thinking-icon" />
            <span>思考过程</span>
          </summary>
          <div class="thinking-content markdown-body" v-html="renderedThinking" />
        </details>

        <!-- 消息块 -->
        <template v-for="(block, bi) in blocks" :key="bi">
          <!-- 工具调用卡片 -->
          <ToolCallCard
            v-if="block.type === 'tool_call'"
            :tool-name="block.toolName"
            :status="block.status"
            :output="block.output"
            :duration-ms="block.durationMs"
            class="block-spacing"
          />

          <!-- 审批卡片 -->
          <ApprovalCard
            v-else-if="block.type === 'approval' && getApprovalBlock(block).status === 'pending'"
            :tool-name="getApprovalBlock(block).toolName"
            :tool-arguments="getApprovalBlock(block).toolArguments"
            :approval-id="getApprovalBlock(block).approvalId"
            :reason="getApprovalBlock(block).reason"
            class="block-spacing"
            @approve="emit('approve', bi)"
            @deny="emit('deny', bi)"
          />

          <!-- 审批已处理 -->
          <div
            v-else-if="block.type === 'approval' && getApprovalBlock(block).status !== 'pending'"
            class="approval-resolved block-spacing"
            :class="getApprovalBlock(block).status"
          >
            <KunIcon :name="getApprovalBlock(block).status === 'approved' ? 'lucide:check-circle' : 'lucide:x-circle'" />
            <span>{{ getApprovalBlock(block).status === 'approved' ? '已允许' : '已拒绝' }}：{{ getApprovalBlock(block).toolName }}</span>
          </div>
        </template>

        <!-- 正文 -->
        <div
          v-if="message.content"
          ref="contentRef"
          class="message-content markdown-body"
          v-html="renderedContent"
        />

        <!-- 流式指示器 -->
        <div v-if="isStreaming && !blocks.length" class="streaming-indicator">
          <span class="dot" /><span class="dot" /><span class="dot" />
        </div>

        <!-- 重新生成按钮 -->
        <div v-if="showRegenerate" class="message-actions">
          <KunButton
            class="action-btn"
            size="sm"
            variant="flat"
            icon
            is-icon-only
            title="重新生成"
            @click="emit('regenerate')"
          >
            <template #icon>
              <KunIcon name="lucide:refresh-cw" />
            </template>
          </KunButton>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.chat-message {
  display: flex;
  gap: 12px;
  padding: 16px 0;
}

.chat-message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 16px;
}

.chat-message.user .message-avatar {
  background: var(--kun-color-primary, #3b82f6);
  color: white;
}

.chat-message.assistant .message-avatar {
  background: var(--kun-color-bg-elevated, #f3f4f6);
  color: var(--kun-color-text, #374151);
}

.message-body {
  max-width: 80%;
  min-width: 0;
}

.chat-message.user .message-body {
  text-align: right;
}

.message-role {
  font-size: 12px;
  font-weight: 600;
  color: var(--kun-color-text-secondary, #9ca3af);
  margin-bottom: 4px;
}

.message-content {
  font-size: 14px;
  line-height: 1.6;
  color: var(--kun-color-text, #1f2937);
}

.user-content {
  background: var(--kun-color-primary, #3b82f6);
  color: white;
  padding: 10px 14px;
  border-radius: 12px 12px 2px 12px;
  display: inline-block;
  text-align: left;
  word-break: break-word;
}

.chat-message.user .message-role {
  text-align: right;
}

.block-spacing {
  margin: 8px 0;
}

/* Markdown */
.markdown-body :deep(p) { margin: 0 0 8px; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(code) {
  background: var(--kun-color-bg-elevated, #f3f4f6);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.markdown-body :deep(pre) {
  background: var(--kun-color-bg-elevated, #f3f4f6);
  padding: 12px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
  position: relative;
}
.markdown-body :deep(pre code) { background: none; padding: 0; }

/* 代码块复制按钮 */
.markdown-body :deep(.copy-btn) {
  position: absolute;
  top: 6px;
  right: 6px;
  background: var(--kun-color-bg, #fff);
  border: 1px solid var(--kun-color-border, #d1d5db);
  border-radius: 4px;
  padding: 4px 6px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
  color: var(--kun-color-text-secondary, #6b7280);
  display: flex;
  align-items: center;
}
.markdown-body :deep(pre:hover .copy-btn) { opacity: 1; }
.markdown-body :deep(.copy-btn:hover) {
  background: var(--kun-color-bg-hover, #f3f4f6);
  color: var(--kun-color-text, #374151);
}
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 20px; margin: 4px 0; }
.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--kun-color-border, #d1d5db);
  padding-left: 12px;
  margin: 8px 0;
  color: var(--kun-color-text-secondary, #6b7280);
}
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) {
  margin: 12px 0 4px;
  font-weight: 600;
}
.markdown-body :deep(a) { color: var(--kun-color-primary, #3b82f6); text-decoration: none; }
.markdown-body :deep(a:hover) { text-decoration: underline; }

/* Thinking */
.thinking-block {
  margin-bottom: 8px;
  border: 1px solid var(--kun-color-border, #e5e7eb);
  border-radius: 8px;
  overflow: hidden;
}
.thinking-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--kun-color-text-secondary, #6b7280);
  background: var(--kun-color-bg-elevated, #f9fafb);
  cursor: pointer;
  user-select: none;
}
.thinking-header:hover { background: var(--kun-color-bg-hover, #f3f4f6); }
.thinking-icon { font-size: 14px; }
.thinking-content {
  padding: 8px 12px;
  font-size: 13px;
  color: var(--kun-color-text-secondary, #6b7280);
  border-top: 1px solid var(--kun-color-border, #e5e7eb);
}

/* Approval resolved */
.approval-resolved {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
}
.approval-resolved.approved {
  background: #ecfdf5;
  color: #059669;
}
.approval-resolved.denied {
  background: #fef2f2;
  color: #dc2626;
}

/* Streaming */
.streaming-indicator {
  display: flex;
  gap: 4px;
  padding-top: 8px;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--kun-color-text-secondary, #9ca3af);
  animation: pulse 1.4s infinite;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* Actions */
.message-actions {
  display: flex;
  gap: 4px;
  padding-top: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}
.chat-message:hover .message-actions { opacity: 1; }
.action-btn {
  padding: 0;
  width: 28px;
  height: 28px;
  font-size: 14px;
}
</style>
