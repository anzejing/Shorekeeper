# Shorekeeper 开发进度

> 最后更新：2026-08-07

## 架构完成度

```
层级                    模块                状态        提交
─────────────────────────────────────────────────────────────
UI (Vue)               聊天界面             ✅ 完成      8660dff
UI (Vue)               Skills 管理页         ✅ 完成      55f701f
UI (Vue)               记忆管理页           ✅ 完成      b017a05
UI (Vue)               权限审批页           ❌ 未开始    -
API                    chat                ✅ 完成      6a8483a
API                    memory              ✅ 完成      0860fd7
API                    skill               ✅ 完成      b5776f3
API                    permission          ✅ 完成      b7e04f3
API                    approval            ✅ 完成      b7e04f3
API                    config              ✅ 完成      (早期)
API                    runtime             ✅ 完成      (早期)
─────────────────────────────────────────────────────────────
Assistant Service      chat API            ✅ 完成      6a8483a
─────────────────────────────────────────────────────────────
Business: Memory       全部                ✅ 完成      0860fd7
Business: Skill        全部 + 插件支持      ✅ 完成      b5776f3 / 1b8ce30
Business: Permission   全部                ✅ 完成      b7e04f3
Business: Workflow      -                   ❌ 预留      -
─────────────────────────────────────────────────────────────
ToolRegistry           注册/执行           ✅ 完成      b5776f3
Tools: Memory          3 个                ✅ 完成      0860fd7
Tools: 通用            3 个                ✅ 完成      3319442
─────────────────────────────────────────────────────────────
Runtime Adapter        全部                ✅ 完成      (早期)
LiteLLM                集成                ✅ 完成      (早期)
─────────────────────────────────────────────────────────────
数据目录               ~/.shorekeeper/     ✅ 完成      64a8174
测试                   后端 337 个          ✅ 通过      (最新)
```

## 已验证的端到端流程

| 测试 | 状态 | 说明 |
|---|---|---|
| 基本对话 | ✅ | LLM 正常回复 |
| 流式对话 (SSE) | ✅ | 文本实时增量输出 |
| Memory write_memory | ✅ | 写入长期记忆 |
| Memory search_memory | ✅ | 跨会话记忆召回（中文整句查询） |
| Permission 拦截 | ✅ | bash_execute 触发 REQUIRE_APPROVAL |
| Approval 审批通过 | ✅ | 创建审批 → 允许 → 执行 → 回复 |
| Approval 审批拒绝 | ✅ | 拒绝 → 工具不执行 → AI 说明被拒 |
| Run 暂停/恢复 | ✅ | WAITING → Resume → COMPLETED |
| 多轮上下文 | ✅ | 同一会话上下文连贯 |
| 停止生成 | ✅ | run 正确取消 |
| 重新生成 | ✅ | 重新生成指定消息（含被取消消息） |
| 会话管理 | ✅ | 新建 / 切换 / 删除（前后端一致） |
| 会话删除确认 | ✅ | KunUI 确认框（取消/确定） |
| 审批过期清理 | ✅ | 定时任务自动标记 expired |

## 开发记录

### 2026-08-07（渐进式披露 + 输入缓存设计讨论）

调研 OpenAI / Anthropic / DeepSeek 官方缓存文档，确认渐进式披露与缓存命中的兼容设计（无代码改动）：

- **关键修正**：OpenAI 官方明确 tools 必须 identical 才能命中缓存（此前假设 tools 在顶层不参与缓存是错的）
- **Anthropic 官方方案**：defer_loading + tool search，发现的工具定义以 tool_reference 块追加到对话历史末尾 → 前缀不动 → 缓存保留
- **设计确认**：system 固定目录（每工具一行摘要）+ tools 固定核心集 + 单调追加激活 + 自实现 tool_search 工具
- 完整设计文档：`docs/progressive-disclosure-design.md`

### 2026-08-07（Agent Plugins 插件适配 + 统一安装入口）

**功能**：适配 [Agent Plugins v1.0.0](https://agent-plugins.org) 标准的 Skills 组件 + 统一安装入口：

| 提交 | 内容 |
|---|---|
| 1b8ce30 | 插件发现：plugin.json 校验（闭包 schema/name 约束/路径安全）+ 插件目录扫描 + 命名空间（plugin-name/skill-name）+ SKILL.md 兼容 metadata.version |
| 1c16256 | 统一安装：POST /api/skills/install 自动判断 SKILL.md / zip / tar.gz（zip slip/bomb/符号链接防护）；插件删除 API |
| fe1550d | 前端：来源标记、安装弹窗多格式、插件删除（确认框提示影响范围） |

**插件包格式**：`~/.shorekeeper/plugins/{name}/`（plugin.json + skills/*/SKILL.md），逻辑名 `plugin-name/skill-name`。

**统一安装自动判断**：
- 单 SKILL.md → 独立 Skill（原逻辑）
- 压缩包含 plugin.json → 插件（plugins/ + 命名空间）
- 压缩包为 Skill 目录 → 独立 Skill（含附带脚本）

**浏览器端到端测试**覆盖：插件 zip 安装（来源标记/提示）、单 SKILL.md 安装、非法文件 400、插件删除（确认框 + API/FS/UI 一致）。

**修复的 Bug（2 个）**：

| # | 问题 | 修复 |
|---|---|---|
| 1 | PluginLoader 未同步 store，插件 skill 状态不持久化 | scan 时 upsert 数据库记录 |
| 2 | install_skill 写附带文件时未创建子目录 | 写入前 mkdir 父目录 |

**验证**：前端 build 通过，后端 337 测试（+47 新增）无回归。

### 2026-08-07（记忆管理页面 + 浏览器端到端测试）

**功能**：记忆管理页面（纯前端，后端 API 已就绪），三个 Tab：

| 提交 | 内容 |
|---|---|
| b017a05 | 对话历史 Tab：会话列表（标题/时间/消息数）+ 标题过滤 + 消息抽屉（角色标识/长消息展开）+ 删除会话 |
| c15082c | 长期记忆 Tab：记忆列表 + 分类筛选 + 编辑抽屉（内容/分类/置信度 slider）+ 删除记忆 |
| 01d96ad | 搜索 Tab：搜索消息+长期记忆，结果类型标注 + 相关度，点击消息结果跳转 /chat/{id} |

**浏览器端到端测试**覆盖：历史列表/过滤/消息查看/删除、记忆列表/分类筛选/编辑保存/删除、搜索/结果/跳转/空状态。

**测试发现并修复的 Bug（2 个）**：

| # | 问题 | 修复 |
|---|---|---|
| 1 | KunTabPanel 单独使用时未传 value prop，内容带 hidden 属性不显示 | 传 value 匹配激活判断 |
| 2 | 刷新按钮只刷新会话列表，不刷新记忆 | 按当前 Tab 刷新对应数据 |

**验证**：前端 build 通过，后端 290 测试无回归。

### 2026-08-07（Skills 管理页面 + 浏览器端到端测试）

**功能**：Skills 管理页面（纯前端，后端 API 已就绪）：

| 提交 | 内容 |
|---|---|
| 55f701f | 列表页：搜索 + 分类筛选 + 启用/禁用开关 + 刷新（api/skill.ts + stores/skills.ts + SkillsView + 路由） |
| daae435 | 详情抽屉：基本信息 + 能力说明（SKILL.md 全文）+ config JSON 编辑；安装弹窗（上传 SKILL.md + 可选目录名）；卸载确认 |

**浏览器端到端测试**（agent-browser + MiMo 识图）覆盖：列表渲染、搜索过滤、分类筛选、开关切换持久化、详情/config 编辑、非法 JSON 校验、安装（上传 SKILL.md）、卸载（确认框）。

**测试发现并修复的 Bug（3 个）**：

| # | 问题 | 修复 |
|---|---|---|
| 1 | 分类筛选选项缺失：categoryOptions 在 setup 顶层创建（非响应式），load() 前 categories 为空 | 改为 computed |
| 2 | config 填合法 JSON 后错误提示不自动清除，保存按钮持续禁用 | 监听 configText 变化清除 configError |
| 3 | 安装弹窗取消/安装按钮不渲染：KunModal 无 footer slot | 按钮移入 default slot |

**验证**：前端 build 通过，后端 290 测试无回归。

### 2026-08-06（浏览器端到端测试 + 功能修复）

**背景**：使用 agent-browser 对前端进行真实浏览器测试（mimo 模型识图确认界面状态），覆盖工具审批、多轮对话、记忆召回等核心流程。

**测试发现并修复的 Bug（8 个）**：

| # | 模块 | 问题 | 修复 |
|---|---|---|---|
| 1 | 审批流程 | `ToolApprovalRequested` 事件缺 `approval_id` 字段，前端 resolve 请求 404，审批流程死循环 | 事件增加 `approval_id` 字段并透传 |
| 2 | 审批流程 | `update_run_context` 从未被调用，审批记录 run_id/session_id 永远为空 | execute/resume 时同步拦截器上下文 |
| 3 | 审批流程 | `find_approved_by_tool` 不检查过期，历史批准（如 echo hello）永久自动放行 | 增加 expires_at 过期检查 |
| 4 | 审批流程 | 拒绝后 resume 找不到 denied 审批，重复创建新审批无限挂起 | denied 审批 → Reject 回填给模型 |
| 5 | Run 执行 | `asyncio.wait_for` 超时会取消 Agent Loop task，run 被意外取消 | 改用 `asyncio.wait`（只等待不取消） |
| 6 | Run 执行 | chat_stream 双重执行竞态（execute_and_wait + execute 并发） | 重构为单次 execute + `wait_until_terminal` |
| 7 | 前端 SSE | `_processedSequences.clear()` 导致重连重放历史事件，审批块重复出现 | 去掉 clear，依赖序列号去重 |
| 8 | 前端 SSE | 旧连接 onDone 干扰新连接状态（currentRunId 被清空） | 增加连接 id 隔离 |

**P1 体验优化（4 项）**：

| 项 | 内容 |
|---|---|
| 会话删除确认框 | 原生 `confirm()` → KunUI `useKunAlert()` |
| search_memory 搜索 | LIKE AND → OR 语义 + 中文 2-4 字滑动窗口 + 按命中数排序 |
| 审批过期清理 | lifespan 启动后台任务，每 10 分钟 `expire_stale()` |
| 取消消息重新生成 | `showRegenerate` 去除 content 非空限制 |

**测试新增**：search_memory 搜索测试（3 个）、审批管理测试（7 个，含过期清理/按 run 匹配/拒绝语义）。

**验证结论**：
- 后端测试 290 个全部通过
- 前端 `pnpm build` 通过
- 浏览器实测：审批允许/拒绝全流程、多轮对话、跨会话记忆召回、停止/重新生成、会话增删均正常
- LLM function calling 偶发用文本代替工具调用（非阻塞，已从 P0 移除）

## 待解决问题

| 问题 | 优先级 | 说明 |
|---|---|---|
| 渐进式披露实施 | P1 | 设计已确认（docs/progressive-disclosure-design.md）：固定目录 + 单调激活 + tool_search，待实施 |
| MCP 接入 | P1 | 迭代 B：stdio/streamable-http，注册进 ToolRegistry + 审批；天然需要渐进披露约束 |
| 权限审批页 | P1 | 后端 API 就绪（approval/permission），前端无独立页面（当前在聊天内联审批） |
| 会话标题自动生成 | P2 | 当前用消息前 20 字，无自动摘要 |
| 更多工具 | P2 | web_search、python_execute |
| skills.sh 在线安装 | P2 | 需接入外部服务 + 后端执行 npx 的接口 |
| Workflow 模块 | 长期 | 多步骤任务流程、状态恢复 |
| 分布式执行 | 长期 | Temporal 集成 |

## 下一步计划

### 短期（当前迭代）

1. **权限审批页**（可选）
   - 审批列表 / 历史
   - 权限规则管理

### 中期

2. **更多 Tools**
   - web_search
   - python_execute

3. **会话标题自动生成**

4. **skills.sh 在线安装**

### 长期

5. **Workflow 模块**
6. **分布式执行（Temporal）**

## 提交历史

| 提交 | 日期 | 内容 |
|---|---|---|
| 1aac7cc | 2026-08-06 | docs: 更新开发进度 |
| 34a157f | 2026-08-06 | feat: 审批过期定时清理（+审批测试） |
| a1fe56b | 2026-08-06 | feat: 改进 search_memory 搜索（+搜索测试） |
| 97b3d95 | 2026-08-06 | fix: 前端交互优化（KunAlert + 重新生成） |
| 8660dff | 2026-08-06 | feat: 前端聊天界面（流式对话 + 工具审批 + 会话管理） |
| b4811cf | 2026-08-06 | fix: 修复权限与审批流程 |
| 6a8483a | 2026-08-06 | feat: 添加流式对话 API |
| 41ed425 | 2026-08-06 | fix: 修复 Run 执行与恢复逻辑 |
| 7f19ffb | 2026-08-03 | fix: 修复 Permission 模块的 bug |
| 3319442 | 2026-08-03 | feat: 添加通用 Tools — bash_execute, read_file, write_file |
| b7e04f3 | 2026-08-03 | feat: 添加 Permission 模块 — 权限控制与审批管理 |
| 91c9bd8 | 2026-08-03 | fix: 修复 Agent Loop 的 tool call 消息格式 |
| d8c0ea9 | 2026-08-03 | feat: 添加最小对话 API — 验证 Memory + Skill + Runtime 全链路 |
| b5776f3 | 2026-08-03 | feat: 添加 Skill 模块 + ToolRegistry |
| 64a8174 | 2026-08-03 | refactor: 数据目录与代码分离，默认 ~/.shorekeeper/ |
| 0860fd7 | 2026-08-03 | feat: 添加 Memory 模块 — 会话历史与长期记忆管理 |
| 966bee6 | 2026-07-31 | feat: 端到端测试通过 — MiMo API 集成 |
| d456aa3 | 2026-07-31 | feat: 添加 Runtime API 接口层 |
| ec2566b | 2026-07-31 | feat: 添加 NativePythonRuntime 组装层 |
| f7e9eca | 2026-07-31 | feat: 添加 SQLite 持久化层 |
| 8b29e62 | 2026-07-31 | feat: 添加 Runtime 状态机 |
| 7884c40 | 2026-07-31 | feat: 添加 Agent Loop 核心循环及依赖接口 |
| 4ef970f | 2026-07-31 | feat: 添加 LiteLLM 薄封装接口层 |
