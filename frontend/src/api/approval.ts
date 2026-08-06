const APPROVAL_BASE = '/api/approvals'
const RUN_BASE = '/api/runs'

export interface ApprovalRequest {
  approval_id: string
  run_id: string
  tool_call_id: string
  tool_name: string
  tool_arguments: Record<string, any>
  status: string
  created_at: string
  expires_at: string | null
  resolved_at: string | null
  reason: string | null
}

export interface ApprovalListResponse {
  approvals: ApprovalRequest[]
  total: number
}

/** 获取待审批列表 */
export async function listPendingApprovals(
  runId?: string,
): Promise<ApprovalListResponse> {
  const params = new URLSearchParams()
  if (runId) params.set('run_id', runId)
  params.set('status', 'pending')
  const res = await fetch(`${APPROVAL_BASE}?${params}`)
  if (!res.ok) throw new Error(`Failed to list approvals: ${res.status}`)
  return res.json()
}

/** 审批/拒绝 */
export async function resolveApproval(
  approvalId: string,
  approved: boolean,
  reason?: string,
): Promise<ApprovalRequest> {
  const res = await fetch(`${APPROVAL_BASE}/${approvalId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      approved,
      scope: 'session',
      reason: reason || null,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `Failed to resolve approval: ${res.status}`)
  }
  return res.json()
}

/** 恢复暂停的 Run */
export async function resumeRun(
  runId: string,
  approved: boolean,
  idempotencyKey: string,
  reason?: string,
): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`${RUN_BASE}/${runId}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      approved,
      idempotency_key: idempotencyKey,
      reason: reason || null,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `Failed to resume run: ${res.status}`)
  }
  return res.json()
}

/** 取消 Run */
export async function cancelRun(
  runId: string,
  reason?: string,
): Promise<void> {
  const res = await fetch(`${RUN_BASE}/${runId}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason: reason || '用户取消' }),
  })
  if (!res.ok) throw new Error(`Failed to cancel run: ${res.status}`)
}
