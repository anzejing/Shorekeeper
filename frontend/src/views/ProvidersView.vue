<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useKunMessage, useKunAlert } from '@kungal/ui-vue'
import { useModelsStore } from '../stores/models'
import ProviderFormModal from '../components/ProviderFormModal.vue'
import type { ModelProvider } from '../api/models'

const store = useModelsStore()

onMounted(async () => {
  await store.init()
  // 加载所有已配置 provider 的模型列表
  for (const p of store.providers) {
    await store.loadModels(p.provider_id)
  }
})

// ─── 目录同步 ────────────────────────────────────────────

async function handleSyncCatalog() {
  try {
    const res = await store.syncCatalogData()
    useKunMessage(
      res.status === 'updated' ? '目录已更新' : '目录已是最新（无变化）',
      res.status === 'updated' ? 'success' : 'info',
    )
  } catch (e: any) {
    useKunMessage(e.message || '同步失败', 'error')
  }
}

// ─── Provider 弹窗 ───────────────────────────────────────

const showProviderModal = ref(false)
const editingProvider = ref<ModelProvider | null>(null)
const importProviderId = ref('')
const importBaseUrl = ref('')

function openAddProvider() {
  editingProvider.value = null
  importProviderId.value = ''
  importBaseUrl.value = ''
  showProviderModal.value = true
}

function openEditProvider(provider: ModelProvider) {
  editingProvider.value = provider
  importProviderId.value = ''
  importBaseUrl.value = ''
  showProviderModal.value = true
}

async function onProviderSaved() {
  await store.loadProviders()
  // 加载新增 provider 的模型
  for (const p of store.providers) {
    if (!store.modelsByProvider[p.provider_id]) {
      await store.loadModels(p.provider_id)
    }
  }
}

// ─── Provider 启用/隐藏 ──────────────────────────────────

async function handleToggleProvider(provider: ModelProvider, enabled: boolean) {
  if (!enabled) {
    const isCurrent = store.current?.provider_id === provider.provider_id
    const ok = await useKunAlert({
      title: '隐藏服务商',
      message: isCurrent
        ? `「${provider.name}」是当前模型所在服务商，隐藏后将清空当前模型选择。确定继续？`
        : `确定隐藏「${provider.name}」？隐藏后其模型不会出现在聊天选择器，可在编辑中重新启用。`,
    })
    if (!ok) return
  }
  try {
    await store.update(provider.provider_id, { enabled })
    // 若隐藏的是当前模型所在 provider → 后端已清空 current，本地同步
    if (!enabled && store.current?.provider_id === provider.provider_id) {
      await store.loadCurrent()
    }
    useKunMessage(
      enabled ? `已启用: ${provider.name}` : `已隐藏: ${provider.name}`,
      'success',
    )
  } catch (e: any) {
    useKunMessage(e.message || '操作失败', 'error')
  }
}

// ─── 展开模型 ────────────────────────────────────────────

const expandedProvider = ref<string | null>(null)
// 各 provider 展开区的“添加模型”输入框引用
const addModelInputs = ref<Record<string, any>>({})

async function handleToggleModels(providerId: string) {
  if (expandedProvider.value === providerId) {
    expandedProvider.value = null
    return
  }
  expandedProvider.value = providerId
  if (!store.modelsByProvider[providerId]) {
    await store.loadModels(providerId)
  }
}

async function handleAddModel(providerId: string, input: HTMLInputElement | null) {
  const modelId = input?.value?.trim()
  if (!modelId) return
  try {
    await store.add(providerId, modelId)
    useKunMessage(`已添加模型: ${modelId}`, 'success')
    if (input) input.value = ''
  } catch (e: any) {
    useKunMessage(e.message || '添加失败', 'error')
  }
}

async function handleRemoveModel(providerId: string, modelId: string) {
  const ok = await useKunAlert({
    title: '删除模型',
    message: `确定删除「${modelId}」？`,
  })
  if (!ok) return
  try {
    await store.removeModelEntry(providerId, modelId)
    useKunMessage(`已删除: ${modelId}`, 'success')
  } catch (e: any) {
    useKunMessage(e.message || '删除失败', 'error')
  }
}

async function handleSyncModels(providerId: string) {
  try {
    const res = await store.syncModels(providerId)
    useKunMessage(`已同步 ${res.count} 个模型`, 'success')
  } catch (e: any) {
    useKunMessage(e.message || '同步失败', 'error')
  }
}

async function handleRemoveProvider(provider: ModelProvider) {
  const ok = await useKunAlert({
    title: '删除服务商',
    message: `确定删除「${provider.name}」及其全部模型？此操作不可恢复。`,
  })
  if (!ok) return
  try {
    await store.remove(provider.provider_id)
    useKunMessage(`已删除: ${provider.name}`, 'success')
  } catch (e: any) {
    useKunMessage(e.message || '删除失败', 'error')
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
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-xl font-bold">服务商管理</h2>
        <p class="text-xs text-gray-500 mt-1">
          管理已添加的 LLM 服务商；models.dev 目录同步
        </p>
      </div>
      <KunButton variant="flat" color="primary" icon @click="openAddProvider">
        <template #icon>
          <KunIcon name="lucide:plus" />
        </template>
        <span>添加服务商</span>
      </KunButton>
    </div>

    <!-- models.dev 目录同步 -->
    <KunCard variant="flat" class="p-4 mb-4">
      <div class="flex items-center justify-between gap-4">
        <div class="min-w-0">
          <div class="text-sm font-semibold">models.dev 公开目录</div>
          <div class="text-xs text-gray-500 mt-1">
            <template v-if="store.catalogStatus?.has_cache">
              数据日期: {{ store.catalogStatus.data_date || '未知' }}
              · 上次同步: {{ store.catalogStatus.synced_at ? new Date(store.catalogStatus.synced_at).toLocaleString() : '从未' }}
              · {{ store.catalogStatus.provider_count }} providers / {{ store.catalogStatus.model_count }} models
            </template>
            <template v-else>
              尚未同步。添加服务商前建议先同步目录（用于搜索服务商与模型预填）。
            </template>
          </div>
        </div>
        <KunButton
          variant="flat"
          color="primary"
          icon
          :loading="store.catalogSyncing"
          @click="handleSyncCatalog"
        >
          <template #icon>
            <KunIcon name="lucide:download-cloud" />
          </template>
          <span>同步目录</span>
        </KunButton>
      </div>
    </KunCard>

    <!-- 服务商列表 -->
    <div v-if="store.providersLoading" class="flex justify-center py-12">
      <KunLoading />
    </div>

    <div v-else-if="store.providers.length === 0" class="py-12">
      <KunNull
        description="暂无服务商。点击右上角「添加服务商」开始配置。"
      >
        <template #actions>
          <KunButton variant="flat" color="primary" @click="openAddProvider">
            添加服务商
          </KunButton>
        </template>
      </KunNull>
    </div>

    <div v-else class="flex flex-col gap-3">
      <KunCard
        v-for="provider in store.providers"
        :key="provider.provider_id"
        variant="flat"
        class="p-4"
      >
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 mb-1">
              <span class="font-semibold text-sm">{{ provider.name }}</span>
              <KunChip size="xs" variant="flat">{{ kindLabel[provider.kind] }}</KunChip>
              <KunChip v-if="provider.source === 'catalog'" size="xs" color="info">
                目录导入
              </KunChip>
              <KunChip v-if="!provider.enabled" size="xs" color="warning">已隐藏</KunChip>
              <KunChip v-if="store.current?.provider_id === provider.provider_id" size="xs" color="primary">
                当前
              </KunChip>
            </div>
            <div class="text-xs text-gray-600 mb-1">
              <code class="bg-gray-100 px-1 rounded">{{ provider.base_url || '(官方端点)' }}</code>
            </div>
            <div class="text-xs text-gray-500">
              API Key: {{ provider.api_key || '(未设置)' }}
              · 模型数: {{ (store.modelsByProvider[provider.provider_id] || []).length }}
            </div>
          </div>

          <div class="flex items-center gap-1 flex-shrink-0">
            <div class="flex items-center gap-1 mr-1" title="启用/隐藏服务商">
              <KunSwitch
                :model-value="provider.enabled"
                size="sm"
                @update:model-value="handleToggleProvider(provider, $event)"
              />
            </div>
            <KunButton variant="flat" size="sm" icon @click="handleToggleModels(provider.provider_id)">
              <template #icon>
                <KunIcon :name="expandedProvider === provider.provider_id ? 'lucide:chevron-up' : 'lucide:chevron-down'" />
              </template>
              <span>模型</span>
            </KunButton>
            <KunButton variant="flat" size="sm" icon title="从 /models 端点同步" @click="handleSyncModels(provider.provider_id)">
              <template #icon>
                <KunIcon name="lucide:refresh-cw" />
              </template>
              <span>同步</span>
            </KunButton>
            <KunButton variant="flat" size="sm" icon @click="openEditProvider(provider)">
              <template #icon>
                <KunIcon name="lucide:pencil" />
              </template>
              <span>编辑</span>
            </KunButton>
            <KunButton variant="flat" size="sm" color="error" icon @click="handleRemoveProvider(provider)">
              <template #icon>
                <KunIcon name="lucide:trash-2" />
              </template>
            </KunButton>
          </div>
        </div>

        <!-- 模型列表展开 -->
        <div v-if="expandedProvider === provider.provider_id" class="mt-3 border-t pt-3">
          <div class="flex flex-col gap-2">
            <div
              v-for="model in store.modelsByProvider[provider.provider_id] || []"
              :key="model.model_id"
              class="flex items-center justify-between px-2 py-1 rounded hover:bg-gray-50"
            >
              <div class="flex items-center gap-2 min-w-0">
                <span class="text-sm">{{ model.display_name }}</span>
                <code class="text-xs bg-gray-100 px-1 rounded">{{ model.litellm_name }}</code>
                <KunChip
                  v-if="!model.enabled"
                  size="xs"
                  color="warning"
                >
                  已隐藏
                </KunChip>
                <KunChip
                  v-if="model.metadata?.tool_call === false"
                  size="xs"
                  color="warning"
                  title="该模型可能不支持工具调用"
                >
                  无工具调用
                </KunChip>
                <KunChip
                  v-if="store.current?.provider_id === provider.provider_id && store.current?.model_id === model.model_id"
                  size="xs"
                  color="primary"
                >
                  当前
                </KunChip>
              </div>
              <button
                class="text-gray-400 hover:text-red-500 p-1"
                title="删除模型"
                @click="handleRemoveModel(provider.provider_id, model.model_id)"
              >
                <KunIcon name="lucide:x" style="font-size: 14px" />
              </button>
            </div>

            <!-- 添加模型 -->
            <div class="flex gap-2 mt-1">
              <KunInput
                :ref="(el: any) => addModelInputs[provider.provider_id] = el"
                placeholder="输入模型 id 添加，如 deepseek-v4-flash"
                size="sm"
                class="flex-1"
              />
              <KunButton
                variant="flat"
                size="sm"
                @click="handleAddModel(provider.provider_id, addModelInputs[provider.provider_id]?.$el?.querySelector('input'))"
              >
                添加
              </KunButton>
            </div>
          </div>
        </div>
      </KunCard>
    </div>

    <!-- Provider 表单弹窗 -->
    <ProviderFormModal
      :show="showProviderModal"
      :editing="editingProvider"
      :import-provider-id="importProviderId"
      :import-base-url="importBaseUrl"
      @close="showProviderModal = false"
      @saved="onProviderSaved"
    />
  </div>
</template>
