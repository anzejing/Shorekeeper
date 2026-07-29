<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
</script>

<template>
  <div class="flex h-screen">
    <AppSidebar />
    <main class="flex-1 overflow-y-auto p-6">
      <RouterView />
    </main>
  </div>
  <KunMessageProvider />
  <KunAlertProvider />
</template>
