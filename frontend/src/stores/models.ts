import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  fetchModels,
  addModel,
  removeModel,
  setModelEnabled as setModelEnabledApi,
  syncProviderModels,
  fetchCatalogStatus,
  syncCatalog,
  fetchCatalogProviders,
  fetchCurrent,
  setCurrent,
  clearCurrent,
  type ModelProvider,
  type ModelEntry,
  type CurrentModel,
  type CatalogProvider,
  type CatalogStatus,
} from '../api/models'

export const useModelsStore = defineStore('models', () => {
  // ─── Provider ─────────────────────────────────────────
  const providers = ref<ModelProvider[]>([])
  const providersLoading = ref(false)

  // ─── 模型 ─────────────────────────────────────────────
  const modelsByProvider = ref<Record<string, ModelEntry[]>>({})
  const modelsLoading = ref(false)

  // ─── 目录 ─────────────────────────────────────────────
  const catalogStatus = ref<CatalogStatus | null>(null)
  const catalogProviders = ref<CatalogProvider[]>([])
  const catalogLoading = ref(false)
  const catalogSyncing = ref(false)

  // ─── 全局当前模型 ─────────────────────────────────────
  const current = ref<CurrentModel | null>(null)

  const currentLabel = computed(() => {
    if (!current.value) return ''
    return current.value.display_name || current.value.model_id
  })

  const hasCurrentModel = computed(() => current.value !== null)

  // ─── Provider ─────────────────────────────────────────

  async function loadProviders() {
    providersLoading.value = true
    try {
      providers.value = await fetchProviders()
    } finally {
      providersLoading.value = false
    }
  }

  async function create(body: Parameters<typeof createProvider>[0]) {
    const provider = await createProvider(body)
    providers.value.push(provider)
    await loadProviders()
    return provider
  }

  async function update(providerId: string, body: Partial<ModelProvider>) {
    const provider = await updateProvider(providerId, body)
    const idx = providers.value.findIndex((p) => p.provider_id === providerId)
    if (idx !== -1) providers.value[idx] = provider
    return provider
  }

  async function remove(providerId: string) {
    await deleteProvider(providerId)
    providers.value = providers.value.filter((p) => p.provider_id !== providerId)
    delete modelsByProvider.value[providerId]
    // 若删除的是当前模型所在 provider → 后端已清空，本地同步
    if (current.value?.provider_id === providerId) {
      current.value = null
    }
  }

  // ─── 模型 ─────────────────────────────────────────────

  async function loadModels(providerId: string) {
    modelsLoading.value = true
    try {
      const models = await fetchModels(providerId)
      modelsByProvider.value[providerId] = models
    } finally {
      modelsLoading.value = false
    }
  }

  async function add(providerId: string, modelId: string) {
    const entry = await addModel(providerId, modelId)
    const list = modelsByProvider.value[providerId] || []
    list.push(entry)
    modelsByProvider.value[providerId] = list
    return entry
  }

  async function removeModelEntry(providerId: string, modelId: string) {
    await removeModel(providerId, modelId)
    modelsByProvider.value[providerId] = (
      modelsByProvider.value[providerId] || []
    ).filter((m) => m.model_id !== modelId)
    if (
      current.value?.provider_id === providerId &&
      current.value?.model_id === modelId
    ) {
      current.value = null
    }
  }

  async function setModelEnabled(
    providerId: string,
    modelId: string,
    enabled: boolean,
  ) {
    const entry = await setModelEnabledApi(providerId, modelId, enabled)
    const list = modelsByProvider.value[providerId] || []
    const idx = list.findIndex((m) => m.model_id === modelId)
    if (idx !== -1) list[idx] = entry
    // 隐藏的是当前模型 → 后端已清空，本地同步
    if (
      !enabled &&
      current.value?.provider_id === providerId &&
      current.value?.model_id === modelId
    ) {
      current.value = null
    }
    return entry
  }

  async function syncModels(providerId: string) {
    const res = await syncProviderModels(providerId)
    await loadModels(providerId)
    return res
  }

  // ─── 目录 ─────────────────────────────────────────────

  async function loadCatalogStatus() {
    catalogStatus.value = await fetchCatalogStatus()
  }

  async function syncCatalogData() {
    catalogSyncing.value = true
    try {
      const res = await syncCatalog()
      await loadCatalogStatus()
      await loadCatalogProviders('')
      return res
    } finally {
      catalogSyncing.value = false
    }
  }

  async function loadCatalogProviders(search: string) {
    catalogLoading.value = true
    try {
      catalogProviders.value = await fetchCatalogProviders(search)
    } finally {
      catalogLoading.value = false
    }
  }

  // ─── 全局当前模型 ─────────────────────────────────────

  async function loadCurrent() {
    current.value = await fetchCurrent()
  }

  async function setCurrentModel(providerId: string, modelId: string) {
    current.value = await setCurrent(providerId, modelId)
  }

  async function clearCurrentModel() {
    await clearCurrent()
    current.value = null
  }

  async function init() {
    await Promise.all([loadProviders(), loadCurrent(), loadCatalogStatus()])
  }

  return {
    providers,
    providersLoading,
    modelsByProvider,
    modelsLoading,
    catalogStatus,
    catalogProviders,
    catalogLoading,
    catalogSyncing,
    current,
    currentLabel,
    hasCurrentModel,
    loadProviders,
    create,
    update,
    remove,
    loadModels,
    add,
    removeModelEntry,
    setModelEnabled,
    syncModels,
    loadCatalogStatus,
    syncCatalogData,
    loadCatalogProviders,
    loadCurrent,
    setCurrentModel,
    clearCurrentModel,
    init,
  }
})
