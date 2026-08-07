<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useKunMessage } from '@kungal/ui-vue'
import { useSkillsStore } from '../stores/skills'
import SkillDetailDrawer from '../components/SkillDetailDrawer.vue'
import type { Skill } from '../api/skill'

const store = useSkillsStore()

onMounted(() => {
  store.load()
})

// ─── 分类筛选选项（动态生成，需响应式以等待列表加载） ───
const categoryOptions = computed(() => [
  { value: null, label: '全部分类' },
  ...store.categories.map((c) => ({ value: c, label: c })),
])

// ─── 详情抽屉 ───
const selectedSkill = ref<Skill | null>(null)
const savingConfig = ref(false)

function openDetail(skill: Skill) {
  selectedSkill.value = skill
}

function closeDetail() {
  selectedSkill.value = null
}

async function handleSaveConfig(config: Record<string, any>) {
  if (!selectedSkill.value) return
  savingConfig.value = true
  try {
    const updated = await store.saveConfig(selectedSkill.value.name, config)
    selectedSkill.value = updated
    useKunMessage('配置已保存', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '保存失败', 'error')
  } finally {
    savingConfig.value = false
  }
}

async function handleUninstall(name: string) {
  const skill = selectedSkill.value
  // 插件 skill → 卸载整个插件
  if (skill?.plugin_name) {
    try {
      await store.uninstallPlugin(skill.plugin_name)
      selectedSkill.value = null
      useKunMessage(`已卸载插件: ${skill.plugin_name}`, 'success')
    } catch (e: any) {
      useKunMessage(e.message || '卸载失败', 'error')
    }
    return
  }
  // 独立 skill
  try {
    await store.uninstall(name)
    selectedSkill.value = null
    useKunMessage(`已卸载 Skill: ${name}`, 'success')
  } catch (e: any) {
    useKunMessage(e.message || '卸载失败', 'error')
  }
}

// ─── 安装弹窗 ───
const showInstallModal = ref(false)
const installFile = ref<File | null>(null)
const installTargetName = ref('')
const installing = ref(false)
const installError = ref<string | null>(null)

function openInstallModal() {
  installFile.value = null
  installTargetName.value = ''
  installError.value = null
  showInstallModal.value = true
}

async function handleInstall() {
  if (!installFile.value) {
    installError.value = '请选择文件'
    return
  }
  installing.value = true
  installError.value = null
  try {
    const result = await store.install(
      installFile.value,
      installTargetName.value.trim() || undefined,
    )
    showInstallModal.value = false
    if (result.type === 'plugin') {
      useKunMessage(
        `已安装插件 ${result.plugin_name}（含 ${result.skills.length} 个 Skill）`,
        'success',
      )
    } else {
      useKunMessage(`已安装 Skill: ${result.skills[0]?.name || ''}`, 'success')
    }
  } catch (e: any) {
    installError.value = e.message || '安装失败'
  } finally {
    installing.value = false
  }
}
</script>

<template>
  <div class="max-w-4xl mx-auto overflow-y-auto p-6 w-full">
    <!-- 标题栏 -->
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-xl font-bold">Skills</h2>
      <div class="flex items-center gap-2">
        <span v-if="store.skills.length" class="text-xs text-gray-500">
          {{ store.enabledCount }}/{{ store.skills.length }} 已启用
        </span>
        <KunButton variant="flat" icon @click="store.reload()">
          <template #icon>
            <KunIcon name="lucide:refresh-cw" />
          </template>
          <span>刷新</span>
        </KunButton>
        <KunButton variant="flat" color="primary" icon @click="openInstallModal">
          <template #icon>
            <KunIcon name="lucide:upload" />
          </template>
          <span>安装</span>
        </KunButton>
      </div>
    </div>

    <!-- 搜索 + 分类筛选 -->
    <div class="flex items-center gap-2 mb-4">
      <KunInput
        v-model="store.searchQuery"
        class="flex-1"
        placeholder="搜索 Skill 名称或描述..."
        size="sm"
      >
        <template #prefix>
          <KunIcon name="lucide:search" class="search-icon" />
        </template>
      </KunInput>
      <KunSelect
        v-model="store.categoryFilter"
        :options="categoryOptions"
        placeholder="全部分类"
        size="sm"
        class="w-36"
      />
    </div>

    <!-- Loading -->
    <div v-if="store.loading" class="flex justify-center py-12">
      <KunLoading />
    </div>

    <!-- 错误提示 -->
    <KunInfo
      v-else-if="store.error"
      color="error"
      :description="store.error"
      class="mb-4"
    />

    <!-- 列表 -->
    <template v-else>
      <div v-if="store.filteredSkills.length === 0" class="py-12">
        <KunNull
          :description="
            store.searchQuery || store.categoryFilter
              ? '没有匹配的 Skill'
              : '暂无 Skill，可点击右上角「安装」上传 SKILL.md'
          "
        />
      </div>

      <div v-else class="flex flex-col gap-2">
        <KunCard
          v-for="skill in store.filteredSkills"
          :key="skill.name"
          variant="flat"
          class="p-4"
          clickable
          is-hoverable
          @click="openDetail(skill)"
        >
          <div class="flex items-start justify-between gap-4">
            <!-- 左侧：信息 -->
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 mb-1">
                <span class="font-semibold text-sm">{{ skill.name }}</span>
                <KunChip
                  v-if="skill.category"
                  size="xs"
                  variant="flat"
                  color="primary"
                >
                  {{ skill.category }}
                </KunChip>
                <KunChip
                  v-if="skill.plugin_name"
                  size="xs"
                  variant="flat"
                >
                  插件: {{ skill.plugin_name }}
                </KunChip>
                <KunChip v-if="skill.has_scripts" size="xs" variant="flat">
                  scripts
                </KunChip>
              </div>
              <p class="text-xs text-gray-600 mb-1 line-clamp-2">
                {{ skill.description }}
              </p>
              <div class="flex items-center gap-2 text-xs text-gray-400">
                <span v-if="skill.version">v{{ skill.version }}</span>
                <span v-if="skill.author">{{ skill.author }}</span>
                <span class="truncate">{{ skill.path }}</span>
              </div>
            </div>

            <!-- 右侧：启用开关（点击不冒泡到卡片） -->
            <div class="flex-shrink-0" @click.stop>
              <KunSwitch
                :model-value="skill.enabled"
                size="sm"
                @update:model-value="
                  store.toggleEnabled(skill.name, $event).catch(() => {})
                "
              />
            </div>
          </div>
        </KunCard>
      </div>
    </template>

    <!-- 详情抽屉 -->
    <SkillDetailDrawer
      :skill="selectedSkill"
      :saving="savingConfig"
      @close="closeDetail"
      @save-config="handleSaveConfig"
      @uninstall="handleUninstall"
    />

    <!-- 安装弹窗 -->
    <KunModal
      v-model="showInstallModal"
      size="md"
      :is-dismissable="true"
      :is-show-close-button="true"
    >
      <h3 class="text-base font-bold mb-4">安装 Skill</h3>
      <div class="flex flex-col gap-4">
        <div>
          <div class="text-sm font-medium mb-2">SKILL.md 文件</div>
          <KunFileInput
            v-model="installFile"
            accept=".md,.zip,.tar.gz"
            :disabled="installing"
          />
          <p class="text-xs text-gray-400 mt-1">
            支持 SKILL.md 文件或插件压缩包（.zip / .tar.gz，含 plugin.json）
          </p>
        </div>
        <div>
          <div class="text-sm font-medium mb-2">目录名（可选）</div>
          <KunInput
            v-model="installTargetName"
            placeholder="不填则使用 frontmatter 中的 name"
            :disabled="installing"
          />
        </div>

        <KunInfo
          v-if="installError"
          color="error"
          :description="installError"
        />
      </div>

      <div class="flex justify-end gap-2 mt-6">
        <KunButton variant="flat" :disabled="installing" @click="showInstallModal = false">
          取消
        </KunButton>
        <KunButton color="primary" variant="flat" :loading="installing" @click="handleInstall">
          安装
        </KunButton>
      </div>
    </KunModal>
  </div>
</template>

<style scoped>
.search-icon {
  font-size: 14px;
  color: var(--kun-color-text-secondary, #9ca3af);
  flex-shrink: 0;
}
</style>
