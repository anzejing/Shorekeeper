<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  toolName: string
  status: 'running' | 'success' | 'error'
  output?: string
  durationMs?: number
}>()

const toolIcon = computed(() => {
  if (props.toolName === 'bash_execute') return 'lucide:terminal'
  if (props.toolName === 'read_file') return 'lucide:file-text'
  if (props.toolName === 'write_file') return 'lucide:file-edit'
  if (props.toolName.includes('memory')) return 'lucide:brain'
  return 'lucide:wrench'
})

const statusIcon = computed(() => {
  if (props.status === 'running') return 'lucide:loader'
  if (props.status === 'success') return 'lucide:check-circle'
  return 'lucide:x-circle'
})

const statusClass = computed(() => `status-${props.status}`)

const durationText = computed(() => {
  if (!props.durationMs) return ''
  if (props.durationMs < 1000) return `${Math.round(props.durationMs)}ms`
  return `${(props.durationMs / 1000).toFixed(1)}s`
})
</script>

<template>
  <div class="tool-card" :class="statusClass">
    <div class="tool-header">
      <KunIcon :name="toolIcon" class="tool-icon" />
      <span class="tool-name">{{ toolName }}</span>
      <span class="tool-status">
        <KunIcon :name="statusIcon" class="status-icon" />
        <span v-if="durationText" class="duration">{{ durationText }}</span>
      </span>
    </div>
    <div v-if="output" class="tool-output">
      <pre>{{ output }}</pre>
    </div>
  </div>
</template>

<style scoped>
.tool-card {
  border: 1px solid var(--kun-color-border, #e5e7eb);
  border-radius: 8px;
  overflow: hidden;
  max-width: 100%;
  font-size: 13px;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--kun-color-bg-elevated, #f9fafb);
}

.tool-icon {
  font-size: 14px;
  color: var(--kun-color-text-secondary, #6b7280);
}

.tool-name {
  font-weight: 600;
  color: var(--kun-color-text, #374151);
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 12px;
}

.tool-status {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
}

.status-icon {
  font-size: 14px;
}

.status-running .status-icon {
  color: #3b82f6;
  animation: spin 1s linear infinite;
}

.status-success .status-icon {
  color: #10b981;
}

.status-error .status-icon {
  color: #ef4444;
}

.duration {
  font-size: 11px;
  color: var(--kun-color-text-secondary, #9ca3af);
}

.tool-output {
  border-top: 1px solid var(--kun-color-border, #e5e7eb);
}

.tool-output pre {
  margin: 0;
  padding: 8px 12px;
  font-size: 12px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  overflow-x: auto;
  max-height: 200px;
  overflow-y: auto;
  color: var(--kun-color-text, #374151);
  background: var(--kun-color-bg, #ffffff);
  white-space: pre-wrap;
  word-break: break-all;
}

.status-error .tool-output pre {
  color: #dc2626;
  background: #fef2f2;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
