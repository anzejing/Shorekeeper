<script setup lang="ts">
import { onMounted } from 'vue'
import { useSkillsStore } from '../stores/skills'

const store = useSkillsStore()

onMounted(() => {
  store.load()
})

// 分类筛选选项：全部 + 数据中的分类（动态生成）
const categoryOptions = [
  { value: null, label: '全部分类' },
  ...store.categories.map((c) => ({ value: c, label: c })),
]
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
          :description="store.searchQuery || store.categoryFilter ? '没有匹配的 Skill' : '暂无 Skill，点击右上角刷新'"
        />
      </div>

      <div v-else class="flex flex-col gap-2">
        <KunCard
          v-for="skill in store.filteredSkills"
          :key="skill.name"
          variant="flat"
          class="p-4"
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

            <!-- 右侧：启用开关 -->
            <KunSwitch
              :model-value="skill.enabled"
              size="sm"
              @update:model-value="
                store.toggleEnabled(skill.name, $event).catch(() => {})
              "
            />
          </div>
        </KunCard>
      </div>
    </template>
  </div>
</template>

<style scoped>
.search-icon {
  font-size: 14px;
  color: var(--kun-color-text-secondary, #9ca3af);
  flex-shrink: 0;
}
</style>
