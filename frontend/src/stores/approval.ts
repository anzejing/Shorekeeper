import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchApprovals,
  resolveApproval,
  fetchPermissionRules,
  createPermissionRule,
  deletePermissionRule,
  resetPermissionRules,
  type ApprovalRequest,
  type PermissionRule,
  type CreateRuleBody,
  type ResolveApprovalBody,
} from '../api/approval'

export const useApprovalStore = defineStore('approval', () => {
  // ─── 审批 ───
  const approvals = ref<ApprovalRequest[]>([])
  const approvalsLoading = ref(false)
  const approvalsError = ref<string | null>(null)

  const pendingApprovals = computed(() =>
    approvals.value.filter((a) => a.status === 'pending'),
  )
  const resolvedApprovals = computed(() =>
    approvals.value.filter((a) => a.status !== 'pending'),
  )

  async function loadApprovals() {
    approvalsLoading.value = true
    approvalsError.value = null
    try {
      const res = await fetchApprovals()
      approvals.value = res.approvals
    } catch (e: any) {
      approvalsError.value = e.message
    } finally {
      approvalsLoading.value = false
    }
  }

  async function approve(id: string, scope?: string, reason?: string) {
    const body = { approved: true, scope: scope as any, reason }
    const updated = await resolveApproval(id, body)
    const idx = approvals.value.findIndex((a) => a.approval_id === id)
    if (idx !== -1) approvals.value[idx] = updated
    return updated
  }

  async function deny(id: string, reason?: string) {
    const body: ResolveApprovalBody = { approved: false, reason }
    const updated = await resolveApproval(id, body)
    const idx = approvals.value.findIndex((a) => a.approval_id === id)
    if (idx !== -1) approvals.value[idx] = updated
    return updated
  }

  // ─── 权限规则 ───
  const rules = ref<PermissionRule[]>([])
  const rulesLoading = ref(false)
  const rulesError = ref<string | null>(null)

  async function loadRules() {
    rulesLoading.value = true
    rulesError.value = null
    try {
      const res = await fetchPermissionRules()
      rules.value = res.rules
    } catch (e: any) {
      rulesError.value = e.message
    } finally {
      rulesLoading.value = false
    }
  }

  async function addRule(body: CreateRuleBody) {
    const rule = await createPermissionRule(body)
    rules.value.push(rule)
    return rule
  }

  async function removeRule(ruleId: string) {
    await deletePermissionRule(ruleId)
    rules.value = rules.value.filter((r) => r.rule_id !== ruleId)
  }

  async function resetRules() {
    const res = await resetPermissionRules()
    rules.value = res.rules
    return res
  }

  return {
    // 审批
    approvals,
    approvalsLoading,
    approvalsError,
    pendingApprovals,
    resolvedApprovals,
    loadApprovals,
    approve,
    deny,
    // 规则
    rules,
    rulesLoading,
    rulesError,
    loadRules,
    addRule,
    removeRule,
    resetRules,
  }
})
