<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()

const navItems = [
  { path: '/config', label: '配置管理', icon: 'lucide:settings' },
]
</script>

<template>
  <aside class="w-56 border-r border-gray-200 bg-gray-50 flex flex-col p-4">
    <h1 class="text-lg font-bold mb-6">Shorekeeper</h1>
    <nav class="flex flex-col gap-1">
      <RouterLink
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors"
        :class="route.path === item.path
          ? 'bg-blue-100 text-blue-700 font-medium'
          : 'text-gray-600 hover:bg-gray-100'"
      >
        <KunIcon :name="item.icon" class="text-lg" />
        {{ item.label }}
      </RouterLink>
    </nav>
  </aside>
</template>
