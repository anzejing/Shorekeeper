<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  toolName: string
  toolArguments: Record<string, any>
  approvalId?: string
  reason?: string
}>()

const emit = defineEmits<{
  approve: []
  deny: []
}>()

const processing = ref(false)

const formattedArgs = computed(() => {
  try {
    return JSON.stringify(props.toolArguments, null, 2)
  } catch {
    return String(props.toolArguments)
  }
})

const toolIcon = computed(() => {
  if (props.toolName === 'bash_execute') return 'lucide:terminal'
  if (props.toolName === 'read_file') return 'lucide:file-text'
  if (props.toolName === 'write_file') return 'lucide:file-edit'
  if (props.toolName.includes('memory')) return 'lucide:brain'
  return 'lucide:wrench'
})

const toolLabel = computed(() => {
  if (props.toolName === 'bash_execute') return '执行命令'
  if (props.toolName === 'read_file') return '读取文件'
  if (props.toolName === 'write_file') return '写入文件'
  if (props.toolName === 'read_memory') return '读取记忆'
  if (props.toolName === 'write_memory') return '写入记忆'
  if (props.toolName === 'search_memory') return '搜索记忆'
  return props.toolName
})

const commandPreview = computed(() => {
  if (props.toolName === 'bash_execute') {
    return props.toolArguments.command || ''
  }
  if (props.toolName === 'read_file' || props.toolName === 'write_file') {
    return props.toolArguments.path || ''
  }
  return ''
})

async function handleApprove() {
  processing.value = true
  emit('approve')
}

async function handleDeny() {
  processing.value = true
  emit('deny')
}
</script>

<template>
  <div class="approval-card">
    <div class="approval-header">
      <KunIcon name="lucide:shield-alert" class="approval-icon" />
      <span class="approval-title">需要你的确认</span>
    </div>

    <div class="approval-body">
      <div class="tool-info">
        <KunIcon :name="toolIcon" class="tool-icon" />
        <span class="tool-label">{{ toolLabel }}</span>
      </div>

      <div v-if="commandPreview" class="command-preview">
        <code>{{ commandPreview }}</code>
      </div>

      <details class="args-details">
        <summary>查看完整参数</summary>
        <pre class="args-json">{{ formattedArgs }}</pre>
      </details>

      <div v-if="reason" class="approval-reason">
        {{ reason }}
      </div>
    </div>

    <div class="approval-actions">
      <button
        class="btn btn-deny"
        :disabled="processing"
        @click="handleDeny"
      >
        <KunIcon name="lucide:x" />
        <span>拒绝</span>
      </button>
      <button
        class="btn btn-approve"
        :disabled="processing"
        @click="handleApprove"
      >
        <KunIcon name="lucide:check" />
        <span>{{ processing ? '处理中...' : '允许执行' }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.approval-card {
  border: 1px solid #fbbf24;
  border-radius: 12px;
  background: #fffbeb;
  overflow: hidden;
  max-width: 100%;
}

.approval-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #fef3c7;
  border-bottom: 1px solid #fbbf24;
}

.approval-icon {
  color: #d97706;
  font-size: 16px;
}

.approval-title {
  font-size: 13px;
  font-weight: 600;
  color: #92400e;
}

.approval-body {
  padding: 12px 14px;
}

.tool-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.tool-icon {
  font-size: 18px;
  color: #6b7280;
}

.tool-label {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
}

.command-preview {
  margin-bottom: 8px;
}

.command-preview code {
  display: block;
  padding: 8px 12px;
  background: #1f2937;
  color: #f3f4f6;
  border-radius: 6px;
  font-size: 13px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  overflow-x: auto;
  white-space: pre;
}

.args-details {
  margin-bottom: 8px;
}

.args-details summary {
  font-size: 12px;
  color: #6b7280;
  cursor: pointer;
  user-select: none;
}

.args-details summary:hover {
  color: #374151;
}

.args-json {
  margin-top: 4px;
  padding: 8px 12px;
  background: #f3f4f6;
  border-radius: 6px;
  font-size: 12px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  overflow-x: auto;
  max-height: 200px;
  color: #374151;
}

.approval-reason {
  font-size: 12px;
  color: #6b7280;
  font-style: italic;
  margin-bottom: 8px;
}

.approval-actions {
  display: flex;
  gap: 8px;
  padding: 0 14px 12px;
}

.btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-deny {
  background: #fee2e2;
  color: #dc2626;
  border: 1px solid #fecaca;
}

.btn-deny:hover:not(:disabled) {
  background: #fecaca;
}

.btn-approve {
  background: #059669;
  color: white;
}

.btn-approve:hover:not(:disabled) {
  background: #047857;
}
</style>
