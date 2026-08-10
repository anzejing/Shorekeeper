<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useKunMessage, useKunAlert } from '@kungal/ui-vue'
import { useApprovalStore } from '../stores/approval'
import type { CreateRuleBody } from '../api/approval'

const store = useApprovalStore()

onMounted(() => {
  store.loadApprovals()
  store.loadRules()
})

// ─── Tab ───

const activeTab = ref<'approvals' | 'rules'>('approvals')

// ─── 审批状态样式 ───

const statusConfig: Record<string, { label: string; color: string }> = {
  pending: { label: '待审批', color: 'warning' },
  approved: { label: '已批准', color: 'success' },
  denied: { label: '已拒绝', color: 'error' },
  expired: { label: '已过期', color: 'default' },
  cancelled: { label: '已取消', color: 'default' },
  consumed: { label: '已消费', color: 'default' },
}

function getStatusConfig(status: string) {
  return statusConfig[status] || { label: status, color: 'default' }
}

function formatTime(dt: string | null): string {
  if (!dt) return '-'
  const d = new Date(dt)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatArgs(args: Record<string, any>): string {
  const entries = Object.entries(args)
  if (entries.length === 0) return '{}'
  return entries.map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(', ')
}

// ─── 审批操作 ───

const resolvingId = ref<string | null>(null)

async function handleApprove(id: string) {
  resolvingId.value = id
  try {
    await store.approve(id, 'session')
    useKunMessage('已批准', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '操作失败', 'error')
  } finally {
    resolvingId.value = null
  }
}

async function handleDeny(id: string) {
  const ok = await useKunAlert({
    title: '拒绝审批',
    message: '确定拒绝该工具调用？模型将收到拒绝原因。',
  })
  if (!ok) return

  resolvingId.value = id
  try {
    await store.deny(id, '用户拒绝')
    useKunMessage('已拒绝', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '操作失败', 'error')
  } finally {
    resolvingId.value = null
  }
}

// ─── 规则操作 ───

const showAddRuleModal = ref(false)
const addingRule = ref(false)
const addRuleError = ref<string | null>(null)
const newRule = ref<CreateRuleBody>({
  tool_name: '',
  policy: 'allow',
  description: '',
  priority: 0,
})

function openAddRule() {
  newRule.value = { tool_name: '', policy: 'allow', description: '', priority: 0 }
  addRuleError.value = null
  showAddRuleModal.value = true
}

async function handleAddRule() {
  if (!newRule.value.description.trim()) {
    addRuleError.value = '请输入规则描述'
    return
  }
  if (!newRule.value.tool_name && !newRule.value.capability) {
    addRuleError.value = '请填写 tool_name 或 capability'
    return
  }
  addingRule.value = true
  addRuleError.value = null
  try {
    await store.addRule(newRule.value)
    showAddRuleModal.value = false
    useKunMessage('规则已添加', 'success')
  } catch (e: any) {
    addRuleError.value = e.message || '添加失败'
  } finally {
    addingRule.value = false
  }
}

async function handleDeleteRule(ruleId: string, desc: string) {
  const ok = await useKunAlert({
    title: '删除规则',
    message: `确定删除规则「${desc}」？`,
  })
  if (!ok) return
  try {
    await store.removeRule(ruleId)
    useKunMessage('规则已删除', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '删除失败', 'error')
  }
}

async function handleResetRules() {
  const ok = await useKunAlert({
    title: '重置规则',
    message: '确定重置所有规则为默认值？用户自定义规则将被删除。',
  })
  if (!ok) return
  try {
    await store.resetRules()
    useKunMessage('规则已重置', 'success')
  } catch (e: any) {
    useKunMessage(e.message || '重置失败', 'error')
  }
}

const policyOptions = [
  { value: 'allow', label: '允许' },
  { value: 'deny', label: '拒绝' },
  { value: 'require_approval', label: '需要审批' },
]

// ─── 规则层级标签 ───

const layerLabels: Record<string, string> = {
  system_guardrail: '系统',
  session_override: '会话',
  project_rule: '项目',
  user_global_rule: '用户',
  builtin_default: '内置',
}
</script>

<template>
  <div class="max-w-4xl mx-auto overflow-y-auto p-6 w-full">
    <!-- 标题栏 -->
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-xl font-bold">权限审批</h2>
        <p class="text-xs text-gray-500 mt-1">
          管理工具调用审批和权限规则
        </p>
      </div>
      <div class="flex items-center gap-2">
        <KunButton variant="flat" icon @click="store.loadApprovals(); store.loadRules()">
          <template #icon>
            <KunIcon name="lucide:refresh-cw" />
          </template>
          <span>刷新</span>
        </KunButton>
      </div>
    </div>

    <!-- Tab 切换 -->
    <div class="flex gap-1 mb-4 border-b">
      <button
        class="px-4 py-2 text-sm font-medium border-b-2 transition-colors"
        :class="activeTab === 'approvals'
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700'"
        @click="activeTab = 'approvals'"
      >
        审批列表
        <span
          v-if="store.pendingApprovals.length"
          class="ml-1 px-1.5 py-0.5 text-xs rounded-full bg-orange-100 text-orange-600"
        >
          {{ store.pendingApprovals.length }}
        </span>
      </button>
      <button
        class="px-4 py-2 text-sm font-medium border-b-2 transition-colors"
        :class="activeTab === 'rules'
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700'"
        @click="activeTab = 'rules'"
      >
        权限规则
        <span class="ml-1 text-xs text-gray-400">{{ store.rules.length }}</span>
      </button>
    </div>

    <!-- ─── Tab 1: 审批列表 ─── -->
    <template v-if="activeTab === 'approvals'">
      <div v-if="store.approvalsLoading" class="flex justify-center py-12">
        <KunLoading />
      </div>

      <KunInfo
        v-else-if="store.approvalsError"
        color="error"
        :description="store.approvalsError"
        class="mb-4"
      />

      <div v-else-if="store.approvals.length === 0" class="py-12">
        <KunNull description="暂无审批记录。当工具调用需要审批时会显示在这里。" />
      </div>

      <div v-else class="flex flex-col gap-3">
        <!-- 待审批 -->
        <template v-if="store.pendingApprovals.length">
          <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
            待审批 ({{ store.pendingApprovals.length }})
          </div>
          <KunCard
            v-for="a in store.pendingApprovals"
            :key="a.approval_id"
            variant="flat"
            class="p-4 border-l-4 border-orange-400"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 mb-2">
                  <KunIcon name="lucide:wrench" class="text-gray-400" style="font-size: 16px" />
                  <span class="font-semibold text-sm">{{ a.tool_name }}</span>
                  <KunChip size="xs" color="warning" variant="flat">待审批</KunChip>
                </div>
                <div class="text-xs text-gray-600 mb-2 font-mono bg-gray-50 p-2 rounded">
                  {{ formatArgs(a.tool_arguments) }}
                </div>
                <div class="flex items-center gap-3 text-xs text-gray-400">
                  <span>{{ formatTime(a.created_at) }}</span>
                  <span v-if="a.run_id">Run: {{ a.run_id.substring(0, 8) }}...</span>
                </div>
              </div>
              <div class="flex items-center gap-2 flex-shrink-0">
                <KunButton
                  variant="flat"
                  size="sm"
                  color="primary"
                  :loading="resolvingId === a.approval_id"
                  @click="handleApprove(a.approval_id)"
                >
                  批准
                </KunButton>
                <KunButton
                  variant="flat"
                  size="sm"
                  color="error"
                  :loading="resolvingId === a.approval_id"
                  @click="handleDeny(a.approval_id)"
                >
                  拒绝
                </KunButton>
              </div>
            </div>
          </KunCard>
        </template>

        <!-- 已解决 -->
        <template v-if="store.resolvedApprovals.length">
          <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1 mt-2">
            历史记录 ({{ store.resolvedApprovals.length }})
          </div>
          <KunCard
            v-for="a in store.resolvedApprovals"
            :key="a.approval_id"
            variant="flat"
            class="p-4 opacity-70"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 mb-1">
                  <span class="font-medium text-sm">{{ a.tool_name }}</span>
                  <KunChip
                    size="xs"
                    :color="getStatusConfig(a.status).color as any"
                    variant="flat"
                  >
                    {{ getStatusConfig(a.status).label }}
                  </KunChip>
                </div>
                <div class="text-xs text-gray-500 font-mono">
                  {{ formatArgs(a.tool_arguments) }}
                </div>
                <div class="flex items-center gap-3 text-xs text-gray-400 mt-1">
                  <span>{{ formatTime(a.created_at) }}</span>
                  <span v-if="a.resolved_at">解决于 {{ formatTime(a.resolved_at) }}</span>
                  <span v-if="a.reason" class="text-gray-500">{{ a.reason }}</span>
                </div>
              </div>
            </div>
          </KunCard>
        </template>
      </div>
    </template>

    <!-- ─── Tab 2: 权限规则 ─── -->
    <template v-if="activeTab === 'rules'">
      <div class="flex items-center justify-between mb-3">
        <div class="text-xs text-gray-500">
          共 {{ store.rules.length }} 条规则
        </div>
        <div class="flex gap-2">
          <KunButton variant="flat" size="sm" @click="handleResetRules">
            重置默认
          </KunButton>
          <KunButton variant="flat" size="sm" color="primary" @click="openAddRule">
            添加规则
          </KunButton>
        </div>
      </div>

      <div v-if="store.rulesLoading" class="flex justify-center py-12">
        <KunLoading />
      </div>

      <KunInfo
        v-else-if="store.rulesError"
        color="error"
        :description="store.rulesError"
        class="mb-4"
      />

      <div v-else-if="store.rules.length === 0" class="py-12">
        <KunNull description="暂无权限规则。" />
      </div>

      <div v-else class="flex flex-col gap-2">
        <KunCard
          v-for="rule in store.rules"
          :key="rule.rule_id"
          variant="flat"
          class="p-4"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 mb-1">
                <KunChip size="xs" variant="flat">
                  {{ layerLabels[rule.layer] || rule.layer }}
                </KunChip>
                <KunChip
                  size="xs"
                  :color="rule.policy === 'allow' ? 'success' : rule.policy === 'deny' ? 'error' : 'warning'"
                  variant="flat"
                >
                  {{ rule.policy === 'allow' ? '允许' : rule.policy === 'deny' ? '拒绝' : '需审批' }}
                </KunChip>
                <span v-if="rule.tool_name" class="text-sm font-medium">
                  {{ rule.tool_name }}
                </span>
                <span v-if="rule.capability" class="text-sm text-gray-500 font-mono">
                  {{ rule.capability }}
                </span>
              </div>
              <p class="text-xs text-gray-600">{{ rule.description }}</p>
              <div class="flex items-center gap-3 text-xs text-gray-400 mt-1">
                <span>优先级: {{ rule.priority }}</span>
                <span v-if="rule.created_by">创建者: {{ rule.created_by }}</span>
              </div>
            </div>
            <KunButton
              v-if="rule.layer !== 'system_guardrail'"
              variant="flat"
              size="sm"
              color="error"
              icon
              @click="handleDeleteRule(rule.rule_id, rule.description)"
            >
              <template #icon>
                <KunIcon name="lucide:trash-2" />
              </template>
            </KunButton>
          </div>
        </KunCard>
      </div>
    </template>

    <!-- 添加规则弹窗 -->
    <KunModal
      v-model="showAddRuleModal"
      size="md"
      :is-dismissable="true"
      :is-show-close-button="true"
    >
      <h3 class="text-base font-bold mb-4">添加权限规则</h3>
      <div class="flex flex-col gap-4">
        <div>
          <div class="text-sm font-medium mb-1">工具名称</div>
          <KunInput
            v-model="newRule.tool_name!"
            placeholder="如 bash_execute, github/list_repos"
            :disabled="addingRule"
          />
          <p class="text-xs text-gray-400 mt-1">匹配特定工具（与 capability 二选一）</p>
        </div>
        <div>
          <div class="text-sm font-medium mb-1">策略</div>
          <KunSelect
            v-model="newRule.policy"
            :options="policyOptions"
            :disabled="addingRule"
          />
        </div>
        <div>
          <div class="text-sm font-medium mb-1">优先级</div>
          <KunInput
            v-model="newRule.priority!"
            type="number"
            placeholder="0"
            :disabled="addingRule"
          />
          <p class="text-xs text-gray-400 mt-1">数值越大优先级越高</p>
        </div>
        <div>
          <div class="text-sm font-medium mb-1">描述</div>
          <KunInput
            v-model="newRule.description"
            placeholder="如：允许 bash 执行 echo 命令"
            :disabled="addingRule"
          />
        </div>
        <KunInfo v-if="addRuleError" color="error" :description="addRuleError" />
      </div>
      <div class="flex justify-end gap-2 mt-6">
        <KunButton variant="flat" :disabled="addingRule" @click="showAddRuleModal = false">
          取消
        </KunButton>
        <KunButton color="primary" variant="flat" :loading="addingRule" @click="handleAddRule">
          添加
        </KunButton>
      </div>
    </KunModal>
  </div>
</template>
