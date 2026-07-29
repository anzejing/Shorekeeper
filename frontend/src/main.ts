import { createApp } from 'vue'
import { createRouter, createWebHistory, RouterLink } from 'vue-router'
import { createPinia } from 'pinia'
import { KunUI, installKunUIConfig } from '@kungal/ui-vue'
import App from './App.vue'
import './assets/main.css'

const app = createApp(App)

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/config',
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
