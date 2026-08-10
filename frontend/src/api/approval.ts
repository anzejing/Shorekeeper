const BASE = '/api/approvals'
const PERM_BASE = '/api/permissions'
const RUN_BASE = '/api/runs'

// ─── 审批相关 ───

export interface ApprovalRequest {
  approval_id: string
  run_id: string
  tool_call_id: string
  tool_name: string
  tool_arguments: Record<string, any>
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'cancelled' | 'consumed'
  created_at: string
  expires_at: string | null
  resolved_at: string | null
  reason: string | null
}

export interface ApprovalListResponse {
  approvals: ApprovalRequest[]
  total: number
}

export interface ResolveApprovalBody {
  approved: boolean
  scope?: 'run' | 'session' | 'project' | 'global'
  reason?: string
}

// ─── 权限规则相关 ───

export interface PermissionRule {
  rule_id: string
  layer: string
  capability: string | null
  tool_name: string | null
  arguments_pattern: string | null
  conditions: Record<string, any>
  policy: 'allow' | 'deny' | 'require_approval'
  priority: number
  scope_type: string
  scope_id: string | null
  expires_at: string | null
  created_by: string | null
  description: string
  created_at: string
  updated_at: string
}

export interface PermissionListResponse {
  rules: PermissionRule[]
  total: number
}

export interface CreateRuleBody {
  capability?: string
  tool_name?: string
  policy: string
  priority?: number
  description: string
  scope_type?: string
}

async function parseError(res: Response, fallback: string): Promise<Error> {
  const err = await res.json().catch(() => ({ detail: res.statusText }))
  return new Error(err.detail || fallback)
}

// ─── 审批 API ───

export async function fetchApprovals(runId?: string): Promise<ApprovalListResponse> {
  const params = new URLSearchParams()
  if (runId) params.set('run_id', runId)
  const res = await fetch(`${BASE}?${params}`)
  if (!res.ok) throw await parseError(res, '获取审批列表失败')
  return res.json()
}

export async function resolveApproval(
  approvalId: string,
  body: ResolveApprovalBody | boolean,
): Promise<ApprovalRequest> {
  const payload: ResolveApprovalBody = typeof body === 'boolean'
    ? { approved: body, scope: 'session' }
    : body
  const res = await fetch(`${BASE}/${encodeURIComponent(approvalId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw await parseError(res, '审批操作失败')
  return res.json()
}

export async function resumeRun(
  runId: string,
  approved: boolean,
  idempotencyKey: string,
): Promise<void> {
  const res = await fetch(`${RUN_BASE}/${encodeURIComponent(runId)}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approved, idempotency_key: idempotencyKey }),
  })
  if (!res.ok) throw await parseError(res, '恢复 Run 失败')
}

export async function cancelRun(runId: string, reason?: string): Promise<void> {
  const res = await fetch(`${RUN_BASE}/${encodeURIComponent(runId)}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
  if (!res.ok) throw await parseError(res, '取消 Run 失败')
}

// ─── 权限规则 API ───

export async function fetchPermissionRules(): Promise<PermissionListResponse> {
  const res = await fetch(PERM_BASE)
  if (!res.ok) throw await parseError(res, '获取权限规则失败')
  return res.json()
}

export async function createPermissionRule(body: CreateRuleBody): Promise<PermissionRule> {
  const res = await fetch(PERM_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res, '创建规则失败')
  return res.json()
}

export async function deletePermissionRule(ruleId: string): Promise<void> {
  const res = await fetch(`${PERM_BASE}/${encodeURIComponent(ruleId)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw await parseError(res, '删除规则失败')
}

export async function resetPermissionRules(): Promise<PermissionListResponse> {
  const res = await fetch(`${PERM_BASE}/reset`, { method: 'POST' })
  if (!res.ok) throw await parseError(res, '重置规则失败')
  return res.json()
}
