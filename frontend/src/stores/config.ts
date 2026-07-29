import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  fetchConfig,
  updateConfig,
  resetConfig,
  type ConfigGroup,
} from '../api/config'

export const useConfigStore = defineStore('config', () => {
  const groups = ref<ConfigGroup[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load() {
    loading.value = true
    error.value = null
    try {
      groups.value = await fetchConfig()
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function update(key: string, value: any) {
    error.value = null
    try {
      const res = await updateConfig(key, value)
      // Update local state
      for (const g of groups.value) {
        const item = g.items.find((i) => i.key === key)
        if (item) {
          item.value = res.reload_required ? value : res.value
          break
        }
      }
      return res
    } catch (e: any) {
      error.value = e.message
      throw e
    }
  }

  async function reset() {
    error.value = null
    try {
      await resetConfig()
      await load()
    } catch (e: any) {
      error.value = e.message
      throw e
    }
  }

  return { groups, loading, error, load, update, reset }
})
