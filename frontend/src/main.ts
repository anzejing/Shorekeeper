import { createApp } from 'vue'
import { createRouter, createWebHistory, RouterLink } from 'vue-router'
import { createPinia } from 'pinia'
import { KunUI, installKunUIConfig } from '@kungal/ui-vue'
import { registerKunIcons } from '@kungal/ui-core'
import { CUSTOM_ICONS } from './icons'
import App from './App.vue'
import './assets/main.css'

// 注册项目自定义图标（KunUI 仅内置少量 lucide 图标，其余需显式注册）
registerKunIcons(CUSTOM_ICONS)

const app = createApp(App)

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/chat',
    },
    {
      path: '/chat/:sessionId?',
      name: 'chat',
      component: () => import('./views/ChatView.vue'),
    },
    {
      path: '/config',
      name: 'config',
      component: () => import('./views/ConfigView.vue'),
    },
  ],
})

app.use(createPinia())
app.use(router)
app.use(KunUI)

installKunUIConfig(app, {
  linkComponent: RouterLink,
  navigate: (href: string) => router.push(href),
})

app.mount('#app')
