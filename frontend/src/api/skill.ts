const BASE = '/api/skills'

export interface Skill {
  name: string
  description: string
  category: string
  version: string
  author: string
  enabled: boolean
  system_prompt: string
  path: string
  has_scripts: boolean
  config: Record<string, any>
  installed_at: string | null
}

export interface SkillListResponse {
  skills: Skill[]
  total: number
}

async function parseError(res: Response, fallback: string): Promise<Error> {
  const err = await res.json().catch(() => ({ detail: res.statusText }))
  return new Error(err.detail || fallback)
}

/** 获取 Skill 列表 */
export async function fetchSkills(enabled?: boolean): Promise<SkillListResponse> {
  const params = new URLSearchParams()
  if (enabled !== undefined) params.set('enabled', String(enabled))
  const res = await fetch(`${BASE}?${params}`)
  if (!res.ok) throw await parseError(res, `获取 Skill 列表失败: ${res.status}`)
  return res.json()
}

/** 获取 Skill 详情 */
export async function fetchSkill(name: string): Promise<Skill> {
  const res = await fetch(`${BASE}/${encodeURIComponent(name)}`)
  if (!res.ok) throw await parseError(res, `获取 Skill 详情失败: ${res.status}`)
  return res.json()
}

/** 更新 Skill（启用/禁用、配置） */
export async function updateSkill(
  name: string,
  body: { enabled?: boolean; config?: Record<string, any> },
): Promise<Skill> {
  const res = await fetch(`${BASE}/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res, `更新 Skill 失败: ${res.status}`)
  return res.json()
}

/** 安装 Skill（上传 SKILL.md 文件） */
export async function installSkill(
  file: File,
  targetName?: string,
): Promise<Skill> {
  const form = new FormData()
  form.append('skill_md', file)
  if (targetName) form.append('target_name', targetName)
  const res = await fetch(`${BASE}/install`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw await parseError(res, `安装 Skill 失败: ${res.status}`)
  return res.json()
}

/** 卸载 Skill */
export async function uninstallSkill(name: string): Promise<void> {
  const res = await fetch(`${BASE}/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw await parseError(res, `卸载 Skill 失败: ${res.status}`)
}

/** 重新扫描 skills 目录 */
export async function reloadSkills(): Promise<SkillListResponse> {
  const res = await fetch(`${BASE}/reload`, { method: 'POST' })
  if (!res.ok) throw await parseError(res, `刷新 Skill 失败: ${res.status}`)
  return res.json()
}
