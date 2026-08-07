import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchSkills,
  fetchSkill,
  updateSkill,
  installSkill,
  uninstallSkill,
  deletePlugin,
  reloadSkills,
  type Skill,
  type InstallResponse,
} from '../api/skill'

export const useSkillsStore = defineStore('skills', () => {
  const skills = ref<Skill[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // 搜索与分类筛选
  const searchQuery = ref('')
  const categoryFilter = ref<string | null>(null)

  // 分类选项（从数据动态生成，不硬编码）
  const categories = computed(() => {
    const set = new Set(skills.value.map((s) => s.category).filter(Boolean))
    return [...set].sort()
  })

  // 过滤后的列表（名称/描述匹配搜索词 + 分类筛选）
  const filteredSkills = computed(() => {
    const q = searchQuery.value.trim().toLowerCase()
    return skills.value.filter((s) => {
      if (categoryFilter.value && s.category !== categoryFilter.value) return false
      if (!q) return true
      return (
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q)
      )
    })
  })

  const enabledCount = computed(
    () => skills.value.filter((s) => s.enabled).length,
  )

  /** 加载 Skill 列表 */
  async function load() {
    loading.value = true
    error.value = null
    try {
      const res = await fetchSkills()
      skills.value = res.skills
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  /** 切换启用状态（乐观更新，失败回滚） */
  async function toggleEnabled(name: string, enabled: boolean) {
    const idx = skills.value.findIndex((s) => s.name === name)
    if (idx === -1) return
    const prev = skills.value[idx].enabled
    skills.value[idx] = { ...skills.value[idx], enabled }
    try {
      skills.value[idx] = await updateSkill(name, { enabled })
    } catch (e: any) {
      skills.value[idx] = { ...skills.value[idx], enabled: prev }
      error.value = e.message
      throw e
    }
  }

  /** 获取 Skill 详情 */
  async function getDetail(name: string): Promise<Skill> {
    return fetchSkill(name)
  }

  /** 保存 Skill config */
  async function saveConfig(name: string, config: Record<string, any>) {
    const updated = await updateSkill(name, { config })
    const idx = skills.value.findIndex((s) => s.name === name)
    if (idx !== -1) skills.value[idx] = updated
    return updated
  }

  /** 安装（SKILL.md / zip / tar.gz 自动判断） */
  async function install(
    file: File,
    targetName?: string,
  ): Promise<InstallResponse> {
    const result = await installSkill(file, targetName)
    await load()
    return result
  }

  /** 卸载 Skill */
  async function uninstall(name: string) {
    await uninstallSkill(name)
    skills.value = skills.value.filter((s) => s.name !== name)
  }

  /** 卸载插件（删除整个插件及其所有 Skill） */
  async function uninstallPlugin(pluginName: string) {
    await deletePlugin(pluginName)
    skills.value = skills.value.filter((s) => s.plugin_name !== pluginName)
  }

  /** 重新扫描 skills 目录 */
  async function reload() {
    loading.value = true
    error.value = null
    try {
      const res = await reloadSkills()
      skills.value = res.skills
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  return {
    skills,
    loading,
    error,
    searchQuery,
    categoryFilter,
    categories,
    filteredSkills,
    enabledCount,
    load,
    toggleEnabled,
    getDetail,
    saveConfig,
    install,
    uninstall,
    uninstallPlugin,
    reload,
  }
})
