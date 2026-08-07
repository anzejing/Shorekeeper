<script setup lang="ts">
import { ref, watch } from 'vue'
import { useKunAlert } from '@kungal/ui-vue'
import type { Skill } from '../api/skill'

const props = defineProps<{
  skill: Skill | null
  saving?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save-config', config: Record<string, any>): void
  (e: 'uninstall', name: string): void
}>()

// ─── config 编辑 ───
const configText = ref('')
const configError = ref<string | null>(null)

// 切换 Skill 时同步 config 编辑框
watch(
  () => props.skill,
  (skill) => {
    if (skill) {
      configText.value = JSON.stringify(skill.config || {}, null, 2)
      configError.value = null
    }
  },
  { immediate: true },
)

function handleSave() {
  if (!props.skill) return
  let parsed: unknown
  try {
    parsed = JSON.parse(configText.value || '{}')
  } catch {
    configError.value = 'JSON 格式错误'
    return
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    configError.value = 'config 必须是 JSON 对象'
    return
  }
  configError.value = null
  emit('save-config', parsed as Record<string, any>)
}

async function handleUninstall() {
  if (!props.skill) return
  const ok = await useKunAlert({
    title: '卸载 Skill',
    message: `确定卸载 "${props.skill.name}"？将删除 Skill 目录与数据库记录，此操作不可恢复。`,
  })
  if (ok) emit('uninstall', props.skill.name)
}

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}
</script>

<template>
  <KunDrawer
    :model-value="!!skill"
    placement="right"
    size="lg"
    :title="skill?.name || 'Skill 详情'"
    :is-dismissable="true"
    :is-show-close-button="true"
    @update:model-value="(v: boolean) => !v && emit('close')"
  >
    <template v-if="skill">
      <!-- 描述 -->
      <p class="text-sm text-gray-600 mb-4">{{ skill.description }}</p>

      <!-- 基本信息网格 -->
      <div class="info-grid mb-4">
        <div class="info-item">
          <span class="info-label">分类</span>
          <span class="info-value">{{ skill.category || '-' }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">版本</span>
          <span class="info-value">{{ skill.version || '-' }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">作者</span>
          <span class="info-value">{{ skill.author || '-' }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">脚本</span>
          <span class="info-value">{{ skill.has_scripts ? '有' : '无' }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">安装时间</span>
          <span class="info-value">{{ formatDate(skill.installed_at) }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">来源</span>
          <span class="info-value truncate">{{ skill.path }}</span>
        </div>
      </div>

      <!-- 能力说明（SKILL.md body，只读滚动） -->
      <div class="section mb-4">
        <h3 class="section-title">能力说明</h3>
        <pre class="prompt-box">{{ skill.system_prompt || '（无）' }}</pre>
      </div>

      <!-- 配置编辑 -->
      <div class="section mb-4">
        <h3 class="section-title">配置 (JSON)</h3>
        <KunTextarea
          v-model="configText"
          :error="configError || undefined"
          placeholder="{}"
        />
      </div>
    </template>

    <template #footer>
      <div class="flex justify-between items-center">
        <KunButton color="error" variant="flat" icon @click="handleUninstall">
          <template #icon>
            <KunIcon name="lucide:trash-2" />
          </template>
          <span>卸载</span>
        </KunButton>
        <KunButton
          color="primary"
          variant="flat"
          :loading="saving"
          :disabled="!!configError || saving"
          @click="handleSave"
        >
          保存配置
        </KunButton>
      </div>
    </template>
  </KunDrawer>
</template>

<style scoped>
.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px 16px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.info-label {
  font-size: 11px;
  color: var(--kun-color-text-secondary, #9ca3af);
}

.info-value {
  font-size: 13px;
  color: var(--kun-color-text, #111827);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--kun-color-text, #111827);
  margin-bottom: 8px;
}

.prompt-box {
  max-height: 240px;
  overflow-y: auto;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--kun-color-bg-hover, #f3f4f6);
  border-radius: 8px;
  padding: 12px;
  color: var(--kun-color-text, #374151);
}

.config-textarea :deep(textarea) {
  font-family: monospace;
  font-size: 12px;
  min-height: 120px;
}
</style>
