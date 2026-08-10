<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useKunMessage, useKunAlert } from '@kungal/ui-vue'
import { useMCPStore } from '../stores/mcp'
import type { AddMCPServerRequest } from '../api/mcp'

const store = useMCPStore()

onMounted(() => {
  store.load()
})

// ─── 状态样式 ───

const statusConfig: Record<string, { label: string; color: string; icon: string }> = {
  connected: { label: '已连接', color: 'success', icon: 'lucide:check-circle' },
  connecting: { label: '连接中', color: 'warning', icon: 'lucide:loader' },
  disconnected: { label: '已断开', color: 'default', icon: 'lucide:circle' },
  error: { label: '错误', color: 'error', icon: 'lucide:alert-circle' },
}

function getStatusConfig(status: string) {
  return statusConfig[status] || statusConfig.disconnected
}

// ─── 添加弹窗 ───

const showAddModal = ref(false)
const adding = ref(false)
const addError = ref<string | null>(null)
const addForm = ref<AddMCPServerRequest>({
  name: '',
  transport: 'stdio',
  command: '',
  args: [],
  url: '',
})

function openAddModal() {
  addForm.value = {
    name: '',
    transport: 'stdio',
    command: '',
    args: [],
    url: '',
  }
  addError.value = null
  showAddModal.value = true
}

async function handleAdd() {
  if (!addForm.value.name.trim()) {
    addError.value = '请输入服务器名称'
    return
  }
  if (addForm.value.transport === 'stdio' && !addForm.value.command?.trim()) {
    addError.value = 'stdio 传输需要填写启动命令'
    return
  }
  if (addForm.value.transport === 'streamable_http' && !addForm.value.url?.trim()) {
    addError.value = 'HTTP 传输需要填写服务地址'
    return
  }

  adding.value = true
  addError.value = null
  try {
    await store.add(addForm.value)
    showAddModal.value = false
    useKunMessage(`已添加 MCP 服务器: ${addForm.value.name}`, 'success')
  } catch (e: any) {
    addError.value = e.message || '添加失败'
  } finally {
    adding.value = false
  }
}

// ─── 删除 ───

async function handleRemove(name: string) {
  const ok = await useKunAlert({
    title: '删除 MCP 服务器',
    message: `确定删除「${name}」？该服务器的所有工具将被移除。`,
  })
  if (!ok) return

  try {
    await store.remove(name)
    useKunMessage(`已删除: ${name}`, 'success')
  } catch (e: any) {
    useKunMessage(e.message || '删除失败', 'error')
  }
}

// ─── 重连 ───

async function handleReconnect(name: string) {
  try {
    await store.reconnect(name)
    useKunMessage(`重连成功: ${name}`, 'success')
  } catch (e: any) {
    useKunMessage(e.message || '重连失败', 'error')
  }
}

// ─── 参数解析 ───

const argsText = ref('')

function parseArgs(): string[] {
  const text = argsText.value.trim()
  if (!text) return []
  // 按空格分割，支持引号包裹
  const parts: string[] = []
  let current = ''
  let inQuote = false
  let quoteChar = ''
  for (const ch of text) {
    if (inQuote) {
      if (ch === quoteChar) {
        inQuote = false
      } else {
        current += ch
      }
    } else if (ch === '"' || ch === "'") {
      inQuote = true
      quoteChar = ch
    } else if (ch === ' ' || ch === '\t') {
      if (current) {
        parts.push(current)
        current = ''
      }
    } else {
      current += ch
    }
  }
  if (current) parts.push(current)
  return parts
}
</script>

<template>
  <div class="max-w-4xl mx-auto overflow-y-auto p-6 w-full">
    <!-- 标题栏 -->
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-xl font-bold">MCP 服务器</h2>
        <p class="text-xs text-gray-500 mt-1">
          Model Context Protocol — 连接外部工具服务器
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="store.servers.length" class="text-xs text-gray-500">
          {{ store.servers.filter((s) => s.status === 'connected').length }}/{{ store.servers.length }} 已连接
        </span>
        <KunButton variant="flat" icon @click="store.load()">
          <template #icon>
            <KunIcon name="lucide:refresh-cw" />
          </template>
          <span>刷新</span>
        </KunButton>
        <KunButton variant="flat" color="primary" icon @click="openAddModal">
          <template #icon>
            <KunIcon name="lucide:plus" />
          </template>
          <span>添加</span>
        </KunButton>
      </div>
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

    <!-- 空状态 -->
    <div v-else-if="store.servers.length === 0" class="py-12">
      <KunNull
        description="暂无 MCP 服务器。点击右上角「添加」连接一个 MCP 服务器。"
      />
    </div>

    <!-- 服务器列表 -->
    <div v-else class="flex flex-col gap-3">
      <KunCard
        v-for="server in store.servers"
        :key="server.name"
        variant="flat"
        class="p-4"
      >
        <div class="flex items-start justify-between gap-4">
          <!-- 左侧信息 -->
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 mb-2">
              <span class="font-semibold text-sm">{{ server.name }}</span>
              <KunChip
                size="xs"
                :variant="server.status === 'connected' ? 'flat' : 'flat'"
                :color="getStatusConfig(server.status).color as any"
              >
                <KunIcon
                  :name="getStatusConfig(server.status).icon"
                  class="mr-1"
                  style="font-size: 12px"
                />
                {{ getStatusConfig(server.status).label }}
              </KunChip>
              <KunChip size="xs" variant="flat">
                {{ server.transport }}
              </KunChip>
            </div>

            <!-- 配置摘要 -->
            <div class="text-xs text-gray-600 mb-2">
              <template v-if="server.transport === 'stdio'">
                <code class="bg-gray-100 px-1 rounded">
                  {{ server.command }}
                </code>
              </template>
              <template v-else>
                <code class="bg-gray-100 px-1 rounded">
                  {{ server.url }}
                </code>
              </template>
            </div>

            <!-- 工具数 -->
            <div class="text-xs text-gray-500">
              <template v-if="server.status === 'connected'">
                已发现 {{ server.tools_count }} 个工具
              </template>
              <template v-else-if="server.error">
                <span class="text-red-500">{{ server.error }}</span>
              </template>
            </div>
          </div>

          <!-- 右侧操作 -->
          <div class="flex items-center gap-1 flex-shrink-0">
            <KunButton
              variant="flat"
              size="sm"
              icon
              @click="handleReconnect(server.name)"
            >
              <template #icon>
                <KunIcon name="lucide:refresh-cw" />
              </template>
              <span>重连</span>
            </KunButton>
            <KunButton
              variant="flat"
              size="sm"
              color="error"
              icon
              @click="handleRemove(server.name)"
            >
              <template #icon>
                <KunIcon name="lucide:trash-2" />
              </template>
              <span>删除</span>
            </KunButton>
          </div>
        </div>
      </KunCard>
    </div>

    <!-- 添加弹窗 -->
    <KunModal
      v-model="showAddModal"
      size="md"
      :is-dismissable="true"
      :is-show-close-button="true"
    >
      <h3 class="text-base font-bold mb-4">添加 MCP 服务器</h3>

      <div class="flex flex-col gap-4">
        <!-- 名称 -->
        <div>
          <div class="text-sm font-medium mb-1">服务器名称</div>
          <KunInput
            v-model="addForm.name"
            placeholder="如 filesystem, github, slack"
            :disabled="adding"
          />
        </div>

        <!-- 传输类型 -->
        <div>
          <div class="text-sm font-medium mb-1">传输类型</div>
          <KunSelect
            v-model="addForm.transport"
            :options="[
              { value: 'stdio', label: 'stdio（子进程）' },
              { value: 'streamable_http', label: 'HTTP（远程服务）' },
            ]"
            :disabled="adding"
          />
        </div>

        <!-- stdio 配置 -->
        <template v-if="addForm.transport === 'stdio'">
          <div>
            <div class="text-sm font-medium mb-1">启动命令</div>
            <KunInput
              v-model="addForm.command"
              placeholder="如 npx, uvx, python"
              :disabled="adding"
            />
          </div>
          <div>
            <div class="text-sm font-medium mb-1">命令参数</div>
            <KunInput
              v-model="argsText"
              placeholder='如 -y @modelcontextprotocol/server-filesystem /tmp'
              :disabled="adding"
            />
            <p class="text-xs text-gray-400 mt-1">
              多个参数用空格分隔，带空格的参数用引号包裹
            </p>
          </div>
        </template>

        <!-- HTTP 配置 -->
        <template v-else>
          <div>
            <div class="text-sm font-medium mb-1">服务地址</div>
            <KunInput
              v-model="addForm.url"
              placeholder="http://localhost:3001/mcp"
              :disabled="adding"
            />
          </div>
        </template>

        <!-- 错误提示 -->
        <KunInfo v-if="addError" color="error" :description="addError" />
      </div>

      <div class="flex justify-end gap-2 mt-6">
        <KunButton
          variant="flat"
          :disabled="adding"
          @click="showAddModal = false"
        >
          取消
        </KunButton>
        <KunButton
          color="primary"
          variant="flat"
          :loading="adding"
          @click="addForm.args = parseArgs(); handleAdd()"
        >
          添加并连接
        </KunButton>
      </div>
    </KunModal>
  </div>
</template>
