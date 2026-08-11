<script setup lang="ts">
import { computed } from 'vue'
import { useModelsStore } from '../stores/models'
import type { CurrentModel } from '../api/models'

const props = defineProps<{
  model: CurrentModel | null
  compact?: boolean  // 聊天工具条紧凑模式
}>()

const emit = defineEmits<{
  change: [providerId: string, modelId: string]
}>()

const store = useModelsStore()

const selectedProviderId = computed(() => props.model?.provider_id ?? '')

const selectedModels = computed(() => {
  const pid = selectedProviderId.value
  return store.modelsByProvider[pid] || []
})

const providerOptions = computed(() =>
  store.providers
    .filter((p) => p.enabled)
    .map((p) => ({ value: p.provider_id, label: p.name || p.provider_id })),
)

const modelOptions = computed(() =>
  selectedModels.value
    .filter((m) => m.enabled)
    .map((m) => ({
      value: m.model_id,
      label: m.display_name || m.model_id,
    })),
)

async function handleProviderChange(providerId: string) {
  if (!providerId) return
  // 懒加载该 provider 的模型列表
  if (!store.modelsByProvider[providerId]) {
    await store.loadModels(providerId)
  }
  const models = store.modelsByProvider[providerId] || []
  const first = models[0]
  if (first) {
    emit('change', providerId, first.model_id)
  }
}

function handleModelChange(modelId: string) {
  if (!selectedProviderId.value || !modelId) return
  emit('change', selectedProviderId.value, modelId)
}
</script>

<template>
  <div class="model-selector" :class="{ compact }">
    <KunSelect
      v-model="selectedProviderId"
      :options="providerOptions"
      placeholder="选择 Provider"
      size="sm"
      class="selector-provider"
      @update:model-value="handleProviderChange"
    />
    <KunSelect
      :model-value="model?.model_id ?? ''"
      :options="modelOptions"
      placeholder="选择模型"
      size="sm"
      class="selector-model"
      :disabled="!selectedProviderId"
      @update:model-value="handleModelChange"
    />
  </div>
</template>

<style scoped>
.model-selector {
  display: flex;
  gap: 6px;
  align-items: center;
}

.model-selector.compact {
  max-width: 420px;
}

.selector-provider {
  width: 140px;
  flex-shrink: 0;
}

.selector-model {
  min-width: 180px;
  flex: 1;
}
</style>
