<script setup lang="ts">
import { onMounted } from 'vue'
import { useKunMessage, useKunAlert } from '@kungal/ui-vue'
import { useConfigStore } from '../stores/config'
import ConfigItemField from '../components/ConfigItemField.vue'

const store = useConfigStore()

onMounted(() => {
  store.load()
})

async function handleSave(key: string, value: any) {
  try {
    const res = await store.update(key, value)
    if (res?.reload_required) {
      useKunMessage('配置已保存，部分配置需要重启服务才能生效', 'warn')
    } else {
      useKunMessage('配置已保存', 'success')
    }
  } catch (e: any) {
    useKunMessage(e.message || '保存失败', 'error')
  }
}

async function handleReset() {
  const ok = await useKunAlert({
    title: '重置配置',
    message: '确定要将所有配置恢复为默认值吗？此操作不可撤销。',
  })
  if (!ok) return

  try {
    await store.reset()
    useKunMessage('配置已重置为默认值', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '重置失败', 'error')
  }
}
</script>

<template>
  <div class="max-w-3xl mx-auto overflow-y-auto p-6">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-bold">配置管理</h2>
      <KunButton color="error" variant="flat" @click="handleReset">重置为默认值</KunButton>
    </div>

    <!-- Loading -->
    <div v-if="store.loading" class="flex justify-center py-12">
      <KunLoading />
    </div>

    <!-- Error -->
    <KunInfo
      v-else-if="store.error"
      color="error"
      :description="store.error"
      class="mb-4"
    />

    <!-- Config groups -->
    <template v-else>
      <div
        v-for="group in store.groups"
        :key="group.group"
        class="mb-6"
      >
        <details open>
          <summary class="cursor-pointer text-sm font-semibold text-gray-700 py-2 hover:text-blue-600 transition-colors">
            {{ group.group }}
          </summary>
          <KunCard variant="flat" class="mt-2 p-4">
            <ConfigItemField
              v-for="item in group.items"
              :key="item.key"
              :item="item"
              @save="handleSave"
            />
          </KunCard>
        </details>
      </div>
    </template>
  </div>
</template>
