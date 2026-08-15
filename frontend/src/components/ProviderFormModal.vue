<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useKunMessage } from '@kungal/ui-vue'
import { useModelsStore } from '../stores/models'
import { testConnection } from '../api/models'
import type { ModelProvider, ProviderKind } from '../api/models'

const props = defineProps<{
  show: boolean
  editing: ModelProvider | null
  /** 目录导入预填的 provider_id */
  importProviderId?: string
  /** 目录导入预填的 base_url */
  importBaseUrl?: string
}>()

const emit = defineEmits<{
  close: []
  saved: []
}>()

const store = useModelsStore()

const kindOptions = [
  { value: 'openai_like', label: 'OpenAI 兼容（自定义端点）' },
  { value: 'openai', label: 'OpenAI 官方' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'gemini', label: 'Google Gemini' },
]

const form = ref({
  provider_id: '',
  name: '',
  kind: 'openai_like' as ProviderKind,
  base_url: '',
  api_key: '',
  enabled: true,
  use_proxy: false,
  import_models: false,
})

const saving = ref(false)
const error = ref<string | null>(null)

// ─── 测试连接 ────────────────────────────────────────────

const testModelId = ref('')
const testing = ref(false)
const testResult = ref<string | null>(null)

const isCatalogImport = computed(
  () => !!props.importProviderId && !props.editing,
)

watch(
  () => props.show,
  (visible) => {
    if (!visible) return
    error.value = null
    testResult.value = null
    testModelId.value = ''
    if (props.editing) {
      form.value = {
        provider_id: props.editing.provider_id,
        name: props.editing.name,
        kind: props.editing.kind,
        base_url: props.editing.base_url,
        api_key: props.editing.api_key, // 掩码 ***
        enabled: props.editing.enabled,
        use_proxy: props.editing.use_proxy,
        import_models: false,
      }
    } else {
      form.value = {
        provider_id: props.importProviderId || '',
        name: props.importProviderId || '',
        kind: 'openai_like',
        base_url: props.importBaseUrl || '',
        api_key: '',
        enabled: true,
        use_proxy: false,
        import_models: isCatalogImport.value,
      }
    }
  },
)

const canTest = computed(() => !!form.value.provider_id && !!testModelId.value.trim())

async function handleTest() {
  if (!canTest.value) return
  testing.value = true
  testResult.value = null
  try {
    const res = await testConnection(form.value.provider_id, testModelId.value.trim())
    testResult.value = `✅ 连接成功（${res.latency_ms}ms），模型: ${res.model}`
  } catch (e: any) {
    testResult.value = `❌ ${e.message || '连接失败'}`
  } finally {
    testing.value = false
  }
}

// ─── 保存 ────────────────────────────────────────────────

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
  try {
    if (props.editing) {
      await store.update(props.editing.provider_id, {
        name: form.value.name || form.value.provider_id,
        kind: form.value.kind,
        base_url: form.value.base_url,
        api_key: form.value.api_key,
        enabled: form.value.enabled,
        use_proxy: form.value.use_proxy,
      })
      useKunMessage('Provider 已更新', 'success')
    } else {
      await store.create({
        provider_id: form.value.provider_id,
        name: form.value.name || form.value.provider_id,
        kind: form.value.kind,
        base_url: form.value.base_url,
        api_key: form.value.api_key,
        enabled: form.value.enabled,
        use_proxy: form.value.use_proxy,
        source: isCatalogImport.value ? 'catalog' : 'custom',
        import_models: form.value.import_models,
      })
      useKunMessage('Provider 已创建', 'success')
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
    size="md"
    :is-dismissable="true"
    :is-show-close-button="true"
    @update:model-value="(v: boolean) => !v && emit('close')"
  >
    <h3 class="text-base font-bold mb-4">
      {{ editing ? '编辑 Provider' : isCatalogImport ? '从目录导入 Provider' : '添加 Provider' }}
    </h3>

    <div class="flex flex-col gap-4">
      <!-- Provider ID -->
      <div>
        <div class="text-sm font-medium mb-1">Provider ID</div>
        <KunInput
          v-model="form.provider_id"
          placeholder="如 opencode, deepseek, anthropic"
          :disabled="!!editing"
        />
        <p class="text-xs text-gray-400 mt-1">小写字母、数字与连字符</p>
      </div>

      <!-- 名称 -->
      <div>
        <div class="text-sm font-medium mb-1">显示名称</div>
        <KunInput v-model="form.name" placeholder="如 OpenCode Go" />
      </div>

      <!-- 类型 -->
      <div>
        <div class="text-sm font-medium mb-1">类型</div>
        <KunSelect v-model="form.kind" :options="kindOptions" />
      </div>

      <!-- Base URL -->
      <div>
        <div class="text-sm font-medium mb-1">
          Base URL
          <span v-if="form.kind === 'openai_like'" class="text-red-500">*</span>
        </div>
        <KunInput
          v-model="form.base_url"
          :placeholder="
            form.kind === 'openai_like'
              ? 'https://api.example.com/v1（必填）'
              : form.kind === 'openai'
                ? 'https://api.openai.com/v1（留空用官方）'
                : '留空使用官方端点'
          "
        />
      </div>

      <!-- API Key -->
      <div>
        <div class="text-sm font-medium mb-1">API Key</div>
        <KunInput
          v-model="form.api_key"
          type="password"
          :placeholder="editing && form.api_key === '***' ? '（保持不变，输入新值可替换）' : 'sk-...'"
        />
      </div>

      <!-- 目录导入选项 -->
      <div v-if="isCatalogImport" class="flex items-center gap-2">
        <input v-model="form.import_models" type="checkbox" class="accent-blue-600" />
        <span class="text-sm text-gray-600">导入该 provider 的全部模型（含元数据）</span>
      </div>

      <!-- 启用 -->
      <div class="flex items-center justify-between">
        <span class="text-sm font-medium">启用</span>
        <KunSwitch v-model="form.enabled" />
      </div>

      <!-- 走代理 -->
      <div class="flex items-center justify-between">
        <span class="text-sm font-medium">走代理</span>
        <KunSwitch v-model="form.use_proxy" />
      </div>
      <p class="text-xs text-gray-400 -mt-2">
        开启后经全局代理访问该 Provider（需先在 设置 → 代理 中配置并开启代理）
      </p>

      <!-- 测试连接 -->
      <div class="border-t pt-3">
        <div class="text-sm font-medium mb-1">测试连接</div>
        <div class="flex gap-2">
          <KunInput
            v-model="testModelId"
            placeholder="输入模型 id，如 deepseek-v4-flash"
            size="sm"
            class="flex-1"
          />
          <KunButton
            variant="flat"
            size="sm"
            :disabled="!canTest || testing"
            :loading="testing"
            @click="handleTest"
          >
            测试
          </KunButton>
        </div>
        <p v-if="testResult" class="text-xs mt-2" :class="testResult.startsWith('✅') ? 'text-green-600' : 'text-red-500'">
          {{ testResult }}
        </p>
      </div>

      <KunInfo v-if="error" color="error" :description="error" />
    </div>

    <div class="flex justify-end gap-2 mt-6">
      <KunButton variant="flat" :disabled="saving" @click="emit('close')">
        取消
      </KunButton>
      <KunButton
        color="primary"
        variant="flat"
        :loading="saving"
        @click="handleSave"
      >
        {{ editing ? '保存' : '创建' }}
      </KunButton>
    </div>
  </KunModal>
</template>
