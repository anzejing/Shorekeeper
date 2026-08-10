import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  fetchMCPServers,
  addMCPServer,
  removeMCPServer,
  reconnectMCPServer,
  type MCPServer,
  type AddMCPServerRequest,
} from '../api/mcp'

export const useMCPStore = defineStore('mcp', () => {
  const servers = ref<MCPServer[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** 加载服务器列表 */
  async function load() {
    loading.value = true
    error.value = null
    try {
      const res = await fetchMCPServers()
      servers.value = res.servers
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  /** 添加服务器 */
  async function add(request: AddMCPServerRequest): Promise<MCPServer> {
    const server = await addMCPServer(request)
    servers.value.push(server)
    return server
  }

  /** 删除服务器 */
  async function remove(name: string) {
    await removeMCPServer(name)
    servers.value = servers.value.filter((s) => s.name !== name)
  }

  /** 重连服务器 */
  async function reconnect(name: string) {
    const idx = servers.value.findIndex((s) => s.name === name)
    if (idx === -1) return
    // 乐观更新：标记为 connecting
    servers.value[idx] = { ...servers.value[idx], status: 'connecting', error: null }
    try {
      const updated = await reconnectMCPServer(name)
      servers.value[idx] = updated
    } catch (e: any) {
      // 回滚
      servers.value[idx] = {
        ...servers.value[idx],
        status: 'error',
        error: e.message,
      }
      throw e
    }
  }

  return {
    servers,
    loading,
    error,
    load,
    add,
    remove,
    reconnect,
  }
})
