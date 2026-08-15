<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useKunMessage } from '@kungal/ui-vue'
import { useModelsStore } from '../stores/models'
import { fetchCatalogModels, previewProviderModels } from '../api/models'
import type { CatalogProvider, ModelProvider, ProviderKind } from '../api/models'

const props = defineProps<{
  show: boolean
  editing: ModelProvider | null
}>()

const emit = defineEmits<{
  close: []
  saved: []
}>()

const store = useModelsStore()

const isEditing = computed(() => !!props.editing)

const kindLabel: Record<string, string> = {
  openai: 'OpenAI',
  openai_like: 'OpenAI 兼容',
  anthropic: 'Anthropic',
  gemini: 'Gemini',
}

const kindOptions = [
  { value: 'openai_like', label: 'OpenAI 兼容（自定义端点）' },
  { value: 'openai', label: 'OpenAI 官方' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'gemini', label: 'Google Gemini' },
]

// ─── 步骤与模式 ──────────────────────────────────────────

const step = ref<1 | 2>(1)
const mode = ref<'catalog' | 'custom'>('catalog')

// ─── Step1：选择服务商 ───────────────────────────────────

const catalogSearch = ref('')
const selectedCatalog = ref<CatalogProvider | null>(null)
const customName = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

// ─── Step2：配置 ─────────────────────────────────────────

const form = ref({
  provider_id: '',
  name: '',
  kind: 'openai_like' as ProviderKind,
  base_url: '',
  models_url: '',
  api_key: '',
  use_proxy: false,
})

interface CandidateModel {
  id: string
  display_name: string
  metadata: Record<string, any>
}

const models = ref<CandidateModel[]>([])
const selectedModelIds = ref<string[]>([])
const previewLoading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
// 用户是否手动改过 models_url（避免 base_url/kind 变化时被自动覆盖）
const modelsUrlTouched = ref(false)

const allSelected = computed(
  () => models.value.length > 0 && selectedModelIds.value.length === models.value.length,
)

function slugify(s: string) {
  return (
    s
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'provider'
  )
}

function deriveModelsUrl(baseUrl: string, kind: string) {
  const b = baseUrl.trim().replace(/\/+$/, '')
  if (!b) return ''
  if (kind === 'anthropic') return `${b}/v1/models`
  if (kind === 'gemini') return `${b}/v1beta/models`
  return `${b}/models`
}

watch(
  async () => props.show,
  async (visible) => {
    if (!visible) return
    error.value = null
    previewLoading.value = false
    saving.value = false
    modelsUrlTouched.value = false
    models.value = []
    selectedModelIds.value = []

    if (props.editing) {
      // 编辑模式：跳过 Step1，直接配置
      step.value = 2
      mode.value = 'custom'
      const p = props.editing
      form.value = {
        provider_id: p.provider_id,
        name: p.name,
        kind: p.kind,
        base_url: p.base_url,
        models_url: p.models_url || '',
        api_key: p.api_key, // 掩码 ***
        use_proxy: p.use_proxy,
      }
      // 模型列表 = 现有全部条目（含隐藏），勾选 = 启用
      if (!store.modelsByProvider[p.provider_id]) {
        await store.loadModels(p.provider_id)
      }
      const entries = store.modelsByProvider[p.provider_id] || []
      models.value = entries.map((e) => ({
        id: e.model_id,
        display_name: e.display_name,
        metadata: e.metadata || {},
      }))
      selectedModelIds.value = entries
        .filter((e) => e.enabled)
        .map((e) => e.model_id)
    } else {
      step.value = 1
      mode.value = 'catalog'
      catalogSearch.value = ''
      selectedCatalog.value = null
      customName.value = ''
      form.value = {
        provider_id: '',
        name: '',
        kind: 'openai_like',
        base_url: '',
        models_url: '',
        api_key: '',
        use_proxy: false,
      }
    }
  },
)

// ─── Step1 交互 ──────────────────────────────────────────

async function handleCatalogSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(async () => {
    await store.loadCatalogProviders(catalogSearch.value)
  }, 300)
}

async function handleSyncCatalog() {
  try {
    await store.syncCatalogData()
    await store.loadCatalogProviders(catalogSearch.value)
    useKunMessage('目录已同步', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '同步失败', 'error')
  }
}

async function loadCatalogModels(providerId: string) {
  try {
    const data = await fetchCatalogModels(providerId)
    models.value = Object.entries(data).map(([id, meta]: [string, any]) => ({
      id,
      display_name: meta?.name || id,
      metadata: meta || {},
    }))
    selectedModelIds.value = [] // 默认不勾选
  } catch {
    models.value = []
  }
}

function selectCatalog(cp: CatalogProvider) {
  selectedCatalog.value = cp
  mode.value = 'catalog'
  form.value = {
    provider_id: cp.provider_id,
    name: cp.name,
    kind: cp.kind,
    base_url: cp.default_base_url || '',
    models_url: deriveModelsUrl(cp.default_base_url, cp.kind),
    api_key: '',
    use_proxy: false,
  }
  modelsUrlTouched.value = false
  step.value = 2
  loadCatalogModels(cp.provider_id)
}

function goCustom() {
  mode.value = 'custom'
  selectedCatalog.value = null
}

function handleStep1Next() {
  if (mode.value === 'catalog') {
    if (!selectedCatalog.value) {
      error.value = '请先选择一个服务商'
      return
    }
    // selectCatalog 已跳转，此处兜底
    step.value = 2
    return
  }
  if (!customName.value.trim()) {
    error.value = '请输入服务商名称'
    return
  }
  selectedCatalog.value = null
  form.value = {
    provider_id: slugify(customName.value),
    name: customName.value.trim(),
    kind: 'openai_like',
    base_url: '',
    models_url: '',
    api_key: '',
    use_proxy: false,
  }
  models.value = []
  selectedModelIds.value = []
  modelsUrlTouched.value = false
  step.value = 2
}

// ─── Step2 交互 ──────────────────────────────────────────

function handleBaseUrlInput() {
  if (!modelsUrlTouched.value) {
    form.value.models_url = deriveModelsUrl(form.value.base_url, form.value.kind)
  }
}

function handleKindChange() {
  if (!modelsUrlTouched.value) {
    form.value.models_url = deriveModelsUrl(form.value.base_url, form.value.kind)
  }
}

function handleModelsUrlInput() {
  modelsUrlTouched.value = true
}

function toggleSelectAll() {
  selectedModelIds.value = allSelected.value
    ? []
    : models.value.map((m) => m.id)
}

function toggleModel(id: string) {
  const idx = selectedModelIds.value.indexOf(id)
  if (idx === -1) selectedModelIds.value.push(id)
  else selectedModelIds.value.splice(idx, 1)
}

async function handlePreview() {
  if (!form.value.base_url.trim() && !form.value.models_url.trim()) {
    error.value = '请先填写 Base URL 或获取模型地址'
    return
  }
  previewLoading.value = true
  error.value = null
  try {
    const res = await previewProviderModels({
      kind: form.value.kind,
      base_url: form.value.base_url,
      models_url: form.value.models_url || undefined,
      api_key: form.value.api_key || undefined,
      use_proxy: form.value.use_proxy,
    })
    // 合并：保留已勾选交集，新模型默认不勾选
    const kept = new Set(selectedModelIds.value)
    models.value = res.models.map((m) => ({
      id: m.id,
      display_name: m.display_name || m.id,
      metadata: {},
    }))
    selectedModelIds.value = models.value
      .filter((m) => kept.has(m.id))
      .map((m) => m.id)
    useKunMessage(`获取到 ${res.models.length} 个模型`, 'success')
  } catch (e: any) {
    error.value = e.message || '获取模型失败'
  } finally {
    previewLoading.value = false
  }
}

async function handleSave() {
  if (!form.value.provider_id.trim()) {
    error.value = '请输入 Provider ID'
    return
  }
  if (form.value.kind === 'openai_like' && !form.value.base_url.trim()) {
    error.value = 'OpenAI 兼容类型必须填写 Base URL'
    return
  }
  saving.value = true
  error.value = null
  const body = {
    name: form.value.name || form.value.provider_id,
    kind: form.value.kind,
    base_url: form.value.base_url,
    models_url: form.value.models_url,
    api_key: form.value.api_key,
    enabled: props.editing ? props.editing.enabled : true,
    use_proxy: form.value.use_proxy,
    model_ids: selectedModelIds.value,
  }
  try {
    if (props.editing) {
      await store.update(props.editing.provider_id, body)
      useKunMessage('服务商已更新', 'success')
    } else {
      await store.create({
        provider_id: form.value.provider_id,
        ...body,
        source: selectedCatalog.value ? 'catalog' : 'custom',
      })
      useKunMessage('服务商已创建', 'success')
    }
    emit('saved')
    emit('close')
  } catch (e: any) {
    error.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <KunModal
    :model-value="show"
    size="lg"
    scroll-behavior="inside"
    :is-dismissable="true"
    :is-show-close-button="true"
    @update:model-value="(v: boolean) => !v && emit('close')"
  >
    <h3 class="text-base font-bold mb-1">
      {{ isEditing ? '编辑服务商' : '添加服务商' }}
    </h3>
    <p class="text-xs text-gray-500 mb-4">
      {{ step === 1 ? '第 1 步 / 共 2 步：选择服务商' : '第 2 步 / 共 2 步：配置与选择模型' }}
    </p>

    <!-- ═══ Step 1：选择服务商 ═══ -->
    <template v-if="step === 1">
      <div class="flex gap-2 mb-4">
        <KunButton
          variant="flat"
          size="sm"
          :color="mode === 'catalog' ? 'primary' : 'default'"
          @click="mode = 'catalog'"
        >
          从 models.dev 目录选择
        </KunButton>
        <KunButton
          variant="flat"
          size="sm"
          :color="mode === 'custom' ? 'primary' : 'default'"
          @click="goCustom"
        >
          自定义输入
        </KunButton>
      </div>

      <template v-if="mode === 'catalog'">
        <div v-if="!store.catalogStatus?.has_cache" class="mb-3">
          <KunInfo color="warning" description="尚未同步 models.dev 目录，无法搜索服务商。请先同步。" />
          <KunButton
            variant="flat"
            size="sm"
            color="primary"
            class="mt-2"
            :loading="store.catalogSyncing"
            @click="handleSyncCatalog"
          >
            同步目录
          </KunButton>
        </div>
        <template v-else>
          <KunInput
            v-model="catalogSearch"
            placeholder="搜索服务商...（如 deepseek, openai, anthropic）"
            size="sm"
            class="mb-3"
            @input="handleCatalogSearch"
          >
            <template #prefix>
              <KunIcon name="lucide:search" class="search-icon" />
            </template>
          </KunInput>
          <div v-if="store.catalogLoading" class="flex justify-center py-8">
            <KunLoading />
          </div>
          <div v-else-if="store.catalogProviders.length === 0" class="py-6">
            <KunNull description="无匹配的服务商" />
          </div>
          <div v-else class="flex flex-col gap-1 max-h-72 overflow-y-auto">
            <div
              v-for="cp in store.catalogProviders"
              :key="cp.provider_id"
              class="flex items-center justify-between px-3 py-2 rounded border border-gray-100 hover:bg-gray-50 cursor-pointer"
              @click="selectCatalog(cp)"
            >
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium">{{ cp.name }}</span>
                  <KunChip size="xs" variant="flat">{{ kindLabel[cp.kind] }}</KunChip>
                  <span class="text-xs text-gray-400">{{ cp.model_count }} 模型</span>
                </div>
                <div v-if="cp.default_base_url" class="text-xs text-gray-500 truncate">
                  <code class="bg-gray-100 px-1 rounded">{{ cp.default_base_url }}</code>
                </div>
              </div>
              <KunIcon name="lucide:chevron-right" class="text-gray-400 flex-shrink-0" />
            </div>
          </div>
        </template>
      </template>

      <template v-else>
        <div class="text-sm font-medium mb-1">服务商名称</div>
        <KunInput v-model="customName" placeholder="如 my-gateway" />
        <p class="text-xs text-gray-400 mt-1">
          不关联 models.dev 目录；类型与端点将在下一步配置。
        </p>
      </template>
    </template>

    <!-- ═══ Step 2：配置与选择模型 ═══ -->
    <template v-else>
      <div class="flex flex-col gap-4">
        <div>
          <div class="text-sm font-medium mb-1">Provider ID</div>
          <KunInput
            v-model="form.provider_id"
            placeholder="如 deepseek"
            :disabled="!!selectedCatalog"
          />
          <p class="text-xs text-gray-400 mt-1">小写字母、数字与连字符；目录选择后自动带出</p>
        </div>

        <div>
          <div class="text-sm font-medium mb-1">显示名称</div>
          <KunInput v-model="form.name" placeholder="如 DeepSeek" />
        </div>

        <div>
          <div class="text-sm font-medium mb-1">类型</div>
          <KunSelect
            v-model="form.kind"
            :options="kindOptions"
            :disabled="!!selectedCatalog"
            @update:model-value="handleKindChange"
          />
        </div>

        <div>
          <div class="text-sm font-medium mb-1">
            Base URL
            <span v-if="form.kind === 'openai_like'" class="text-red-500">*</span>
          </div>
          <KunInput
            v-model="form.base_url"
            :placeholder="form.kind === 'openai_like' ? 'https://api.example.com/v1' : '留空使用官方端点'"
            @input="handleBaseUrlInput"
          />
          <p class="text-xs text-gray-400 mt-1">已按 models.dev 数据或官方端点预填，可修改</p>
        </div>

        <div>
          <div class="text-sm font-medium mb-1">获取模型地址</div>
          <div class="flex gap-2">
            <KunInput
              v-model="form.models_url"
              placeholder="默认 = base_url + /models"
              class="flex-1"
              @input="handleModelsUrlInput"
            />
            <KunButton
              variant="flat"
              size="sm"
              :loading="previewLoading"
              @click="handlePreview"
            >
              手动获取模型
            </KunButton>
          </div>
          <p class="text-xs text-gray-400 mt-1">点击「手动获取模型」从该地址拉取真实模型列表</p>
        </div>

        <div>
          <div class="text-sm font-medium mb-1">API Key</div>
          <KunInput
            v-model="form.api_key"
            type="password"
            :placeholder="isEditing && form.api_key === '***' ? '（保持不变，输入新值可替换）' : 'sk-...'"
          />
        </div>

        <div class="flex items-center justify-between">
          <span class="text-sm font-medium">走代理</span>
          <KunSwitch v-model="form.use_proxy" />
        </div>
        <p class="text-xs text-gray-400 -mt-2">
          开启后经全局代理访问该服务商（需在 设置 → 代理 中配置）
        </p>

        <!-- 模型选择 -->
        <div class="border-t pt-3">
          <div class="flex items-center justify-between mb-2">
            <div class="text-sm font-medium">
              选择模型（{{ selectedModelIds.length }}/{{ models.length }}）
            </div>
            <KunButton variant="flat" size="sm" @click="toggleSelectAll">
              {{ allSelected ? '取消全选' : '全选' }}
            </KunButton>
          </div>
          <p class="text-xs text-gray-500 mb-2">
            {{
              isEditing
                ? '勾选 = 启用；取消勾选 = 隐藏（记录保留，可在模型页/聊天选择器隐藏）'
                : '仅勾选的模型会导入，并在模型页与聊天选择器展示'
            }}
          </p>
          <div v-if="models.length === 0" class="py-4">
            <KunNull
              description="暂无模型列表。目录未收录或尚未获取；可点击「手动获取模型」拉取。"
            />
          </div>
          <div
            v-else
            class="flex flex-col gap-1 max-h-56 overflow-y-auto border border-gray-100 rounded p-1"
          >
            <div
              v-for="m in models"
              :key="m.id"
              class="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-50"
            >
              <KunCheckBox
                :model-value="selectedModelIds.includes(m.id)"
                @update:model-value="toggleModel(m.id)"
              />
              <span class="text-sm min-w-0 truncate">{{ m.display_name }}</span>
              <code class="text-xs bg-gray-100 px-1 rounded truncate">{{ m.id }}</code>
              <KunChip
                v-if="m.metadata?.tool_call === false"
                size="xs"
                color="warning"
                title="该模型可能不支持工具调用"
              >
                无工具调用
              </KunChip>
            </div>
          </div>
        </div>

        <KunInfo v-if="error" color="error" :description="error" />
      </div>
    </template>

    <!-- 底部操作 -->
    <div class="flex justify-between gap-2 mt-6">
      <KunButton
        v-if="step === 2"
        variant="flat"
        :disabled="saving"
        @click="step = 1"
      >
        上一步
      </KunButton>
      <div class="flex gap-2 ml-auto">
        <KunButton variant="flat" :disabled="saving" @click="emit('close')">取消</KunButton>
        <KunButton
          v-if="step === 1"
          variant="flat"
          color="primary"
          @click="handleStep1Next"
        >
          下一步
        </KunButton>
        <KunButton
          v-else
          color="primary"
          variant="flat"
          :loading="saving"
          @click="handleSave"
        >
          {{ isEditing ? '保存' : '创建' }}
        </KunButton>
      </div>
    </div>
  </KunModal>
</template>

<style scoped>
.search-icon {
  font-size: 14px;
  color: var(--kun-color-text-secondary, #9ca3af);
}
</style>
