<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useKunMessage, useKunAlert } from '@kungal/ui-vue'
import { useModelsStore } from '../stores/models'
import { testConnection } from '../api/models'
import ModelSelector from '../components/ModelSelector.vue'
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

// ─── Tab ───

const activeTab = ref<'models' | 'providers' | 'catalog'>('models')

// ─── Provider 弹窗 ───

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

function openImportProvider(pid: string, _name: string, baseUrl: string) {
  editingProvider.value = null
  importProviderId.value = pid
  importBaseUrl.value = baseUrl
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

// ─── 模型 Tab：切换当前模型 ───

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

// ─── Provider Tab：操作 ───

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
    title: '删除 Provider',
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

// ─── 目录 Tab ───

const catalogSearch = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

async function handleCatalogSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(async () => {
    await store.loadCatalogProviders(catalogSearch.value)
  }, 300)
}

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
</script>

<template>
  <div class="max-w-4xl mx-auto overflow-y-auto p-6 w-full">
    <!-- 标题栏 -->
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-xl font-bold">模型管理</h2>
        <p class="text-xs text-gray-500 mt-1">
          多 Provider / 多 Model 配置，models.dev 目录同步，全局模型切换
        </p>
      </div>
      <KunButton variant="flat" color="primary" icon @click="openAddProvider">
        <template #icon>
          <KunIcon name="lucide:plus" />
        </template>
        <span>添加 Provider</span>
      </KunButton>
    </div>

    <!-- Tab 切换 -->
    <div class="flex gap-1 mb-4 border-b">
      <button
        class="px-4 py-2 text-sm font-medium border-b-2 transition-colors"
        :class="activeTab === 'models'
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700'"
        @click="activeTab = 'models'"
      >
        当前模型
      </button>
      <button
        class="px-4 py-2 text-sm font-medium border-b-2 transition-colors"
        :class="activeTab === 'providers'
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700'"
        @click="activeTab = 'providers'"
      >
        Provider
        <span class="ml-1 text-xs text-gray-400">{{ store.providers.length }}</span>
      </button>
      <button
        class="px-4 py-2 text-sm font-medium border-b-2 transition-colors"
        :class="activeTab === 'catalog'
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700'"
        @click="activeTab = 'catalog'"
      >
        models.dev 目录
      </button>
    </div>

    <!-- ─── Tab 1: 当前模型 ─── -->
    <template v-if="activeTab === 'models'">
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
            description="尚未选择当前模型。请先在「Provider」或「models.dev 目录」Tab 配置 Provider 与模型，然后回到本页选择。"
          >
            <template #actions>
              <KunButton variant="flat" color="primary" @click="activeTab = 'providers'">
                去配置 Provider
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
    </template>

    <!-- ─── Tab 2: Provider ─── -->
    <template v-else-if="activeTab === 'providers'">
      <div v-if="store.providersLoading" class="flex justify-center py-12">
        <KunLoading />
      </div>

      <div v-else-if="store.providers.length === 0" class="py-12">
        <KunNull
          description="暂无 Provider。点击右上角「添加 Provider」或到 models.dev 目录导入。"
        >
          <template #actions>
            <KunButton variant="flat" color="primary" @click="activeTab = 'catalog'">
              浏览目录
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
                <KunChip v-if="!provider.enabled" size="xs" color="warning">已禁用</KunChip>
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
    </template>

    <!-- ─── Tab 3: models.dev 目录 ─── -->
    <template v-else>
      <KunCard variant="flat" class="p-4 mb-4">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm font-semibold">models.dev 公开目录</div>
            <div class="text-xs text-gray-500 mt-1">
              <template v-if="store.catalogStatus?.has_cache">
                数据日期: {{ store.catalogStatus.data_date || '未知' }}
                · 上次同步: {{ store.catalogStatus.synced_at ? new Date(store.catalogStatus.synced_at).toLocaleString() : '从未' }}
                · {{ store.catalogStatus.provider_count }} providers / {{ store.catalogStatus.model_count }} models
              </template>
              <template v-else>
                尚未同步。点击「同步目录」获取公开模型元数据（能力、上下文长度、定价）。
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

      <!-- 搜索 -->
      <KunInput
        v-model="catalogSearch"
        class="mb-3"
        placeholder="搜索 provider...（如 deepseek, openai, anthropic）"
        size="sm"
        @input="handleCatalogSearch"
      >
        <template #prefix>
          <KunIcon name="lucide:search" class="search-icon" />
        </template>
      </KunInput>

      <div v-if="store.catalogLoading" class="flex justify-center py-8">
        <KunLoading />
      </div>

      <div v-else-if="store.catalogProviders.length === 0" class="py-8">
        <KunNull :description="store.catalogStatus?.has_cache ? '无匹配的 provider' : '请先同步目录'" />
      </div>

      <div v-else class="flex flex-col gap-2">
        <KunCard
          v-for="cp in store.catalogProviders"
          :key="cp.provider_id"
          variant="flat"
          class="p-3 flex items-center justify-between"
        >
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium">{{ cp.name }}</span>
              <KunChip size="xs" variant="flat">{{ kindLabel[cp.kind] }}</KunChip>
              <span class="text-xs text-gray-400">{{ cp.model_count }} 模型</span>
            </div>
            <div v-if="cp.api" class="text-xs text-gray-500 truncate">
              <code class="bg-gray-100 px-1 rounded">{{ cp.api }}</code>
            </div>
          </div>
          <KunButton
            variant="flat"
            size="sm"
            color="primary"
            :disabled="store.providers.some((p) => p.provider_id === cp.provider_id)"
            @click="openImportProvider(cp.provider_id, cp.name, cp.api)"
          >
            {{ store.providers.some((p) => p.provider_id === cp.provider_id) ? '已导入' : '导入' }}
          </KunButton>
        </KunCard>
      </div>
    </template>

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

<style scoped>
.search-icon {
  font-size: 14px;
  color: var(--kun-color-text-secondary, #9ca3af);
}
</style>
