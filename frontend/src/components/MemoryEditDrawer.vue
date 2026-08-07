<script setup lang="ts">
import { ref, watch } from 'vue'
import type { MemoryEntry } from '../api/memory'
import { MEMORY_CATEGORIES } from '../stores/memory'

const props = defineProps<{
  memory: MemoryEntry | null
  saving?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', edits: { content: string; category: string; confidence: number }): void
}>()

// 表单状态
const content = ref('')
const category = ref('other')
const confidence = ref(100) // 0-100，保存时映射 0-1

// 切换记忆时同步表单
watch(
  () => props.memory,
  (memory) => {
    if (memory) {
      content.value = memory.content
      category.value = memory.category
      confidence.value = Math.round(memory.confidence * 100)
    }
  },
  { immediate: true },
)

function handleSave() {
  if (!props.memory) return
  if (!content.value.trim()) return
  emit('save', {
    content: content.value.trim(),
    category: category.value,
    confidence: confidence.value / 100,
  })
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
</script>

<template>
  <KunDrawer
    :model-value="!!memory"
    placement="right"
    size="md"
    title="编辑长期记忆"
    :is-dismissable="true"
    :is-show-close-button="true"
    @update:model-value="(v: boolean) => !v && emit('close')"
  >
    <template v-if="memory">
      <div class="flex flex-col gap-4">
        <!-- 内容 -->
        <div>
          <div class="text-sm font-medium mb-2">内容</div>
          <KunTextarea
            v-model="content"
            placeholder="记忆内容"
            :disabled="saving"
          />
        </div>

        <!-- 分类 -->
        <div>
          <div class="text-sm font-medium mb-2">分类</div>
          <KunSelect
            v-model="category"
            :options="MEMORY_CATEGORIES"
            :disabled="saving"
          />
        </div>

        <!-- 置信度 -->
        <div>
          <div class="text-sm font-medium mb-2">
            置信度：{{ confidence }}%
          </div>
          <KunSlider
            v-model="confidence"
            :min="0"
            :max="100"
            :step="5"
            show-value
            :disabled="saving"
          />
        </div>

        <!-- 元信息 -->
        <div class="text-xs text-gray-400">
          创建：{{ formatTime(memory.created_at) }} · 更新：{{ formatTime(memory.updated_at) }}
        </div>
      </div>
    </template>

    <template #footer>
      <div v-if="memory" class="flex justify-end">
        <KunButton
          color="primary"
          variant="flat"
          :loading="saving"
          :disabled="!content.trim() || saving"
          @click="handleSave"
        >
          保存
        </KunButton>
      </div>
    </template>
  </KunDrawer>
</template>
