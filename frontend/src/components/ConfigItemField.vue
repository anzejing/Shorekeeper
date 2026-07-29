<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ConfigItem } from '../api/config'

const props = defineProps<{ item: ConfigItem }>()
const emit = defineEmits<{ save: [key: string, value: any] }>()

const editing = ref(false)
const draft = ref<any>(props.item.value)
const saving = ref(false)
const localError = ref<string | null>(null)

const displayValue = computed(() => {
  if (props.item.secret && !editing.value) return '***'
  return String(props.item.value ?? '')
})

function startEdit() {
  if (props.item.secret) {
    draft.value = ''  // Clear for secret fields
  } else {
    draft.value = props.item.value
  }
  editing.value = true
  localError.value = null
}

function cancelEdit() {
  editing.value = false
  localError.value = null
}

async function handleSave() {
  saving.value = true
  localError.value = null
  try {
    emit('save', props.item.key, draft.value)
    editing.value = false
  } catch (e: any) {
    localError.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="flex items-start justify-between py-3 border-b border-gray-100 last:border-0">
    <div class="flex-1 min-w-0 mr-4">
      <div class="flex items-center gap-2">
        <span class="text-sm font-medium text-gray-800">{{ item.label }}</span>
        <KunBadge v-if="item.required" color="error" variant="flat" class="text-xs">必填</KunBadge>
        <KunBadge v-if="item.secret" color="warn" variant="flat" class="text-xs">敏感</KunBadge>
      </div>
      <p class="text-xs text-gray-500 mt-0.5">{{ item.description }}</p>
      <p class="text-xs text-gray-400 mt-0.5 font-mono">{{ item.key }}</p>
    </div>

    <div class="flex items-center gap-2 shrink-0">
      <!-- Display mode -->
      <template v-if="!editing">
        <span class="text-sm text-gray-700 max-w-[200px] truncate" :title="displayValue">
          {{ displayValue }}
        </span>
        <KunButton size="sm" variant="flat" @click="startEdit">编辑</KunButton>
      </template>

      <!-- Edit mode -->
      <template v-else>
        <!-- Boolean -->
        <KunSwitch
          v-if="item.type === 'boolean'"
          v-model="draft"
        />

        <!-- Select -->
        <KunSelect
          v-else-if="item.type === 'select'"
          v-model="draft"
          :options="item.options?.map(o => ({ label: String(o), value: o })) ?? []"
          class="w-40"
        />

        <!-- Number -->
        <KunInput
          v-else-if="item.type === 'number'"
          v-model="draft"
          type="number"
          class="w-32"
        />

        <!-- String / Path -->
        <KunInput
          v-else
          v-model="draft"
          :type="item.secret ? 'password' : 'text'"
          class="w-48"
        />

        <KunButton size="sm" color="success" :loading="saving" @click="handleSave">保存</KunButton>
        <KunButton size="sm" variant="flat" @click="cancelEdit">取消</KunButton>
      </template>
    </div>

    <!-- Error -->
    <p v-if="localError" class="text-xs text-red-500 mt-1 absolute right-0">{{ localError }}</p>
  </div>
</template>
