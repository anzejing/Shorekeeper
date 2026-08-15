<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useKunMessage, useKunAlert } from '@kungal/ui-vue'
import { useModelsStore } from '../stores/models'
import { testConnection } from '../api/models'
import ModelSelector from '../components/ModelSelector.vue'
import type { ModelEntry, ModelProvider } from '../api/models'

const store = useModelsStore()

onMounted(async () => {
  await store.init()
  // 加载所有已配置 provider 的模型列表
  for (const p of store.providers) {
    await store.loadModels(p.provider_id)
  }
})

// ─── 切换当前模型 ────────────────────────────────────────

async function handleModelChange(providerId: string, modelId: string) {
  try {
    await store.setCurrentModel(providerId, modelId)
    useKunMessage(`当前模型已切换: ${store.currentLabel}`, 'success')
  } catch (e: any) {
    useKunMessage(e.message || '切换失败', 'error')
  }
}

async function handleClearCurrent() {
  const ok = await useKunAlert({
    title: '清空当前模型',
    message: '清空后发送聊天需要重新选择模型。确定继续？',
  })
  if (!ok) return
  await store.clearCurrentModel()
  useKunMessage('当前模型已清空', 'success')
}

// 当前模型测试
const currentTestModel = ref('')
const currentTesting = ref(false)
const currentTestResult = ref<string | null>(null)

const canTestCurrent = computed(
  () => !!store.current && !!currentTestModel.value.trim(),
)

async function handleTestCurrent() {
  if (!store.current || !canTestCurrent.value) return
  currentTesting.value = true
  currentTestResult.value = null
  try {
    const res = await testConnection(
      store.current.provider_id,
      currentTestModel.value.trim(),
    )
    currentTestResult.value = `✅ 连接成功（${res.latency_ms}ms）`
  } catch (e: any) {
    currentTestResult.value = `❌ ${e.message || '连接失败'}`
  } finally {
    currentTesting.value = false
  }
}

// ─── 按 provider 分组的已启用模型 ────────────────────────

const enabledGroups = computed(() => {
  const groups: { provider: ModelProvider; models: ModelEntry[] }[] = []
  for (const p of store.providers) {
    const models = (store.modelsByProvider[p.provider_id] || []).filter(
      (m) => m.enabled,
    )
    if (models.length > 0) groups.push({ provider: p, models })
  }
  return groups
})

function isCurrentModel(providerId: string, modelId: string) {
  return (
    store.current?.provider_id === providerId &&
    store.current?.model_id === modelId
  )
}

async function handleHideModel(
  providerId: string,
  modelId: string,
  isCurrent: boolean,
) {
  const ok = await useKunAlert({
    title: '隐藏模型',
    message: isCurrent
      ? `「${modelId}」是当前模型，隐藏后将清空当前模型选择，需重新选择后才能聊天。确定继续？`
      : `确定隐藏「${modelId}」？隐藏后模型页与聊天选择器将不再显示，可在服务商页编辑该服务商时重新启用。`,
  })
  if (!ok) return
  try {
    await store.setModelEnabled(providerId, modelId, false)
    useKunMessage(`已隐藏: ${modelId}`, 'success')
  } catch (e: any) {
    useKunMessage(e.message || '隐藏失败', 'error')
  }
}

const kindLabel: Record<string, string> = {
  openai: 'OpenAI',
  openai_like: 'OpenAI 兼容',
  anthropic: 'Anthropic',
  gemini: 'Gemini',
}
</script>

<template>
  <div class="max-w-4xl mx-auto overflow-y-auto p-6 w-full">
    <!-- 标题栏 -->
    <div class="mb-4">
      <h2 class="text-xl font-bold">模型管理</h2>
      <p class="text-xs text-gray-500 mt-1">
        全局当前模型与可用模型管理；服务商配置请在「服务商」页操作
      </p>
    </div>

    <!-- 当前模型 -->
    <KunCard variant="flat" class="p-5">
      <div class="text-sm font-semibold mb-3">全局当前模型</div>

      <!-- 已配置 -->
      <template v-if="store.current">
        <div class="flex items-center gap-2 mb-4">
          <KunChip color="primary" size="sm">
            <KunIcon name="lucide:sparkles" class="mr-1" style="font-size: 12px" />
            {{ store.current.litellm_name }}
          </KunChip>
        </div>
        <div class="flex items-center gap-3 mb-4">
          <ModelSelector :model="store.current" @change="handleModelChange" />
          <KunButton variant="flat" size="sm" color="error" @click="handleClearCurrent">
            清空
          </KunButton>
        </div>
        <p class="text-xs text-gray-500">
          聊天页输入框左上方会显示当前模型，可随时切换；对话中途切换后新消息使用新模型，上下文保持连续。
        </p>
      </template>

      <!-- 未配置 -->
      <template v-else>
        <KunNull
          description="尚未选择当前模型。请先启用一个模型并在此选择，或在「服务商」页配置服务商。"
        >
          <template #actions>
            <KunButton variant="flat" color="primary" @click="$router.push('/providers')">
              去服务商页
            </KunButton>
          </template>
        </KunNull>
      </template>
    </KunCard>

    <!-- 测试连接 -->
    <KunCard variant="flat" class="p-5 mt-4">
      <div class="text-sm font-semibold mb-1">测试连接</div>
      <p class="text-xs text-gray-500 mb-3">
        选择一个或输入模型 id，向当前 provider 发送最小请求验证连通性
      </p>
      <div class="flex gap-2">
        <KunInput
          v-model="currentTestModel"
          placeholder="如 deepseek-v4-flash"
          size="sm"
          class="flex-1"
          :disabled="!store.current"
        />
        <KunButton
          variant="flat"
          size="sm"
          :disabled="!canTestCurrent || currentTesting"
          :loading="currentTesting"
          @click="handleTestCurrent"
        >
          测试
        </KunButton>
      </div>
      <p v-if="currentTestResult" class="text-xs mt-2"
        :class="currentTestResult.startsWith('✅') ? 'text-green-600' : 'text-red-500'">
        {{ currentTestResult }}
      </p>
    </KunCard>

    <!-- 已启用模型（按服务商分组） -->
    <template v-if="enabledGroups.length > 0">
      <KunCard variant="flat" class="p-5 mt-4">
        <div class="text-sm font-semibold mb-1">可用模型</div>
        <p class="text-xs text-gray-500 mb-3">
          按服务商分组展示已启用模型；隐藏的模型不显示，可在服务商页编辑对应服务商重新启用。
        </p>
        <div
          v-for="group in enabledGroups"
          :key="group.provider.provider_id"
          class="mb-4 last:mb-0"
        >
          <div class="flex items-center gap-2 mb-2">
            <span class="text-sm font-semibold">{{ group.provider.name }}</span>
            <KunChip size="xs" variant="flat">
              {{ kindLabel[group.provider.kind] }}
            </KunChip>
            <span class="text-xs text-gray-400">{{ group.models.length }} 个模型</span>
          </div>
          <div class="flex flex-col gap-1">
            <div
              v-for="model in group.models"
              :key="model.model_id"
              class="flex items-center justify-between px-2 py-1.5 rounded border border-gray-100 hover:bg-gray-50"
            >
              <div class="flex items-center gap-2 min-w-0">
                <span class="text-sm">{{ model.display_name }}</span>
                <code class="text-xs bg-gray-100 px-1 rounded">{{ model.litellm_name }}</code>
                <KunChip
                  v-if="model.metadata?.tool_call === false"
                  size="xs"
                  color="warning"
                  title="该模型可能不支持工具调用"
                >
                  无工具调用
                </KunChip>
                <KunChip
                  v-if="isCurrentModel(group.provider.provider_id, model.model_id)"
                  size="xs"
                  color="primary"
                >
                  当前
                </KunChip>
              </div>
              <KunButton
                variant="flat"
                size="sm"
                color="warning"
                @click="handleHideModel(group.provider.provider_id, model.model_id, isCurrentModel(group.provider.provider_id, model.model_id))"
              >
                隐藏
              </KunButton>
            </div>
          </div>
        </div>
      </KunCard>
    </template>

    <!-- 无可用模型 -->
    <KunCard v-else variant="flat" class="p-5 mt-4">
      <KunNull
        description="暂无已启用的模型。请先在「服务商」页配置并启用模型，或在服务商编辑中启用隐藏的模型。"
      >
        <template #actions>
          <KunButton variant="flat" color="primary" @click="$router.push('/providers')">
            去服务商页
          </KunButton>
        </template>
      </KunNull>
    </KunCard>
  </div>
</template>
