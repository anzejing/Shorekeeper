# Shorekeeper 开发进度

> 最后更新：2026-08-11

## 进行中的工作

- **模型管理（多 Provider / 多 Model）**：设计文档 `docs/models-management.md` 已定稿（用户已确认），
  实现进行中。完成后替换旧 runtime 单模型机制。

## 架构完成度

```
层级                    模块                状态        提交
─────────────────────────────────────────────────────────────
UI (Vue)               聊天界面             ✅ 完成      8660dff
UI (Vue)               Skills 管理页         ✅ 完成      55f701f
UI (Vue)               记忆管理页           ✅ 完成      b017a05
UI (Vue)               权限审批页           ✅ 完成      (2026-08-10)
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
Tools: 渐进式披露      tool_search/executor ✅ 完成      (2026-08-10)
MCP 模块               连接/发现/执行       ✅ 完成      (2026-08-10)
MCP 管理页面           前端 CRUD            ✅ 完成      (2026-08-10)
─────────────────────────────────────────────────────────────
Runtime Adapter        全部                ✅ 完成      (早期)
LiteLLM                集成                ✅ 完成      (早期)
─────────────────────────────────────────────────────────────
数据目录               ~/.shorekeeper/     ✅ 完成      64a8174
测试                   后端 447 个          ✅ 通过      (最新)
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
| 渐进式披露：tool_search | ✅ | BM25 搜索 MCP 工具，返回完整 schema |
| 渐进式披露：tool_executor | ✅ | 代理执行器 + 参数校验 + 错误反馈 |
| MCP 服务器连接（stdio） | ✅ | 子进程长连接，自动发现工具 |
| MCP 工具注册 | ✅ | ToolRegistry + ToolIndex 双注册 |
| MCP 工具执行 | ✅ | tool_executor → MCPService → call_tool |
| MCP 断开清理 | ✅ | 工具从 registry/index 自动移除 |
| LLM 两步调用模式 | ✅ | tool_search → tool_executor 全链路验证 |
| LLM 参数错误自恢复 | ✅ | 缺参数 → 错误反馈 → LLM 自行修正 |
| LLM 连续多工具 | ✅ | 3 个工具 × 2 步 = 6 步全部成功 |
| MCP 管理页面：添加服务器 | ✅ | 填写表单 → 连接 → 显示工具数 |
| MCP 管理页面：重连 | ✅ | 点击重连 → 状态更新 → toast 提示 |
| MCP 管理页面：删除确认 | ✅ | 确认弹窗 → 确定 → 服务器移除 |
| MCP 管理页面：MiMo 视觉验证 | ✅ | 布局/卡片/弹窗/按钮样式均正常 |
| 权限审批页：审批列表 Tab | ✅ | 空状态/待审批/历史记录分组 |
| 权限审批页：权限规则 Tab | ✅ | 规则列表/标签/策略显示 |
| 权限审批页：MiMo 视觉验证 | ✅ | 布局/Tab 切换/卡片样式均正常 |

## 开发记录

### 2026-08-11（模型管理：文档与设计定稿）

**背景**：旧机制只有单模型（config.yaml runtime 段 + .env 覆盖），改模型需改文件 + 重启。
用户需求：多 Provider/多 Model、models.dev 目录、/models 端点覆盖、全局切换 + 热切换、配置存 DB。

| 修改 | 文件 | 说明 |
|---|---|---|
| 新增 | `docs/models-management.md` | 模型管理完整设计（数据模型/API/数据流/热切换/计量准备） |
| 修改 | `docs/product-spec.md` | 配置管理功能域：Runtime 段废弃，新增 5.6 模型管理 |
| 修改 | `docs/model-config.md` | 标注废弃，指向 models-management.md |
| 修改 | `README.md` | 配置示例更新（见下） |

**关键决策（用户确认）**：
- 侧边栏新增「模型」页（`/models`），与「配置」并列
- 4 种 provider：openai / openai_like / anthropic / gemini
- api_key 等存 SQLite；旧 runtime 段直接删除，.env 覆盖逻辑移除
- 全局当前模型可空可删；为空时聊天提示选择模型
- 模型选择器：输入框左上方二级选择（provider → model），支持测试连接
- models.dev 同步：数据日期显示 + ETag 增量 + 手动同步按钮
- /models 端点同步覆盖 models.dev 不一致数据；元数据为计量页面保留

### 2026-08-11（LLM 切换 DeepSeek V4 Flash + 固定 tools 列表修复）

**背景**：mimo API 配额耗尽（429），LLM 切换到 opencode-go 的 deepseek-v4-flash。

| 修改 | 文件 | 说明 |
|---|---|---|
| 修改 | `~/.shorekeeper/config.yaml` + `backend/.env` | runtime 切换：base_url=https://opencode.ai/zen/go/v1，model=deepseek-v4-flash |
| 修改 | `backend/app/api/chat.py` | tools 列表改为注入固定列表（不再用 registry.get_all_tools） |
| 修改 | `backend/app/main.py` | 组装 fixed_tools（BUILTIN + MEMORY + web_search + PROXY） |
| 修改 | `backend/tests/test_llm_execution.py` | LLM 配置切换 + MCP 工具排除出 LLM tools |
| 修改 | `backend/tests/test_api_chat.py` | 适配 init_chat_api 新签名 |

**修复的问题（DeepSeek V4 Flash 兼容性）**：

| 问题 | 说明 |
|---|---|
| 工具名含 `/` 被拒 | opencode.go 要求工具名匹配 `^[a-zA-Z0-9_-]+$`，MCP 工具命名 server/tool 含 `/` → 400。修复：MCP 工具不直接暴露给 LLM，通过 tool_search/tool_executor 发现执行（本就符合设计 G1：tools 永远不变） |

**验证**：
- LLM 执行度测试 5/5 通过（此前 mimo 配额 429 全部失败）
- 全量 477 测试通过（472 + 5）
- 真实聊天端到端："帮我搜索 opencode.ai" → LLM 自动生成 tool_call web_search → 权限 ALLOW → Brave 真实搜索 → LLM 中文总结 → 回复持久化 ✅

### 2026-08-11（web_search 工具 + pytest 挂起修复）

**功能**：web_search 网络搜索工具（参考 pi-search 插件设计）。

| 新增/修改 | 文件 | 说明 |
|---|---|---|
| 新增 | `backend/app/tools/web_search.py` | ToolDef + 执行器 + 4 服务商适配（Brave/Tavily/Firecrawl/Jina）+ 配置解析 |
| 修改 | `backend/app/config/schema.py` | 新增 `SearchConfig`（4 个 secret key + priority + max_results + timeout） |
| 修改 | `backend/app/config/meta.py` | GROUP_META 增加 search（"搜索"），ConfigView 自动展示 |
| 修改 | `backend/app/main.py` | 注册 web_search + 默认权限规则（ALLOW，只读） |
| 修改 | `backend/pyproject.toml` | 显式声明 aiohttp 依赖 |
| 新增 | `backend/tests/test_web_search.py` | 25 个单元测试（mock HTTP） |
| 新增 | `backend/tests/conftest.py` | 修复 pytest 结束后进程挂起 |

**工具设计**：
- action=search（网页搜索）/ extract（网页正文）/ help（使用指南）
- 按配置优先级自动选择服务商，指定服务商失败自动回退，全部失败返回明确错误
- API Key 解析优先级：config.yaml → 环境变量 → pi-search 配置兜底（4 个 key 已迁移至 ~/.shorekeeper/config.yaml）
- 结果摘要 300 字符 / 正文 6000 字符截断
- 权限：只读 → 默认 ALLOW（与 read_file 一致）

**验证**：
- 后端 472 测试全部通过（447 原有 + 25 新增），进程正常退出
- 真实 API 端到端：Brave 搜索返回真实结果 ✅，Jina 提取网页正文 ✅

**修复的测试基建问题（预先存在）**：

| 问题 | 修复 |
|---|---|
| pytest 全部测试通过后进程永久挂起：aiosqlite 连接未关闭，非守护 worker 线程导致 threading._shutdown 等待 | conftest.py 追踪并统一关闭连接 |

**备注**：test_llm_execution 5 个失败为 mimo API 配额耗尽（429 quota exhausted），预先存在，与本次改动无关。

### 2026-08-10（MCP 配置持久化）

**功能**：MCP 服务器配置持久化到 config.yaml。

| 修改文件 | 变更 |
|---|---|
| `backend/app/api/mcp.py` | 添加/删除服务器后通过 ConfigService 持久化到 config.yaml |
| `backend/app/main.py` | init_mcp_api 传入 config_service |

**验证**：
- API 添加服务器 → config.yaml 出现 mcp.servers 配置 ✅
- API 删除服务器 → config.yaml 中对应配置移除 ✅
- 重启后自动加载 config.yaml 中的 MCP 配置 ✅

### 2026-08-10（权限审批页）

**功能**：权限审批管理页面（前端 + 后端 API 已就绪）。

| 新增/修改 | 文件 | 说明 |
|---|---|---|
| 新增 | `frontend/src/api/approval.ts` | 审批 + 权限规则 API 客户端（含 resumeRun/cancelRun 兼容） |
| 新增 | `frontend/src/stores/approval.ts` | 审批 + 规则状态管理 |
| 新增 | `frontend/src/views/ApprovalView.vue` | 权限审批页面 |
| 修改 | `frontend/src/main.ts` | 添加 /approvals 路由 |
| 修改 | `frontend/src/components/AppSidebar.vue` | 侧边栏添加审批导航 |

**页面功能**：
- **审批列表 Tab**：
  - 待审批列表（橙色边框卡片，显示工具名/参数/时间）
  - 批准/拒绝按钮
  - 历史记录（已批准/已拒绝/已过期）
  - 状态标签（颜色区分）
- **权限规则 Tab**：
  - 规则列表（层级标签 + 策略标签 + 工具名）
  - 添加规则弹窗（工具名/策略/优先级/描述）
  - 删除规则（确认弹窗）
  - 重置默认规则
- 空状态提示
- 刷新按钮

**MiMo 视觉验证**：
- 审批列表 Tab：布局整齐，Tab 切换清晰，空状态友好
- 权限规则 Tab：标签颜色区分明显，按钮位置合理
- 无 UI 问题

### 2026-08-10（MCP 管理页面）

**功能**：MCP 服务器管理页面（前端 + 后端 API）。

| 新增/修改 | 文件 | 说明 |
|---|---|---|
| 新增 | `backend/app/api/mcp.py` | MCP HTTP API（列表/添加/删除/重连） |
| 修改 | `backend/app/main.py` | 注册 MCP API 路由 |
| 新增 | `frontend/src/api/mcp.ts` | MCP API 客户端 |
| 新增 | `frontend/src/stores/mcp.ts` | MCP 状态管理 |
| 新增 | `frontend/src/views/MCPView.vue` | MCP 管理页面 |
| 修改 | `frontend/src/main.ts` | 添加 /mcp 路由 |
| 修改 | `frontend/src/components/AppSidebar.vue` | 侧边栏添加 MCP 导航 |
| 修改 | `frontend/src/icons.ts` | 添加 plug 图标 |

**页面功能**：
- 服务器列表（名称、传输类型、连接状态、工具数量）
- 添加弹窗（支持 stdio / streamable_http 两种传输）
- 重连按钮（断开后重新连接）
- 删除按钮（确认弹窗 → 移除服务器及所有工具）
- 状态标签（已连接/连接中/已断开/错误）
- 空状态提示

**浏览器测试**：
- 添加服务器 → 成功连接 → 显示 3 个工具
- 重连 → 成功 → toast 提示
- 删除 → 确认弹窗 → 确定 → 服务器移除
- MiMo 视觉验证：布局/卡片/弹窗/按钮样式均正常

### 2026-08-10（渐进式披露实施 + MCP 接入 + LLM 执行度验证）

**Phase 1: 渐进式披露基础设施**

| 新增文件 | 说明 |
|---|---|
| `app/tool/index.py` | ToolIndex + BM25 搜索（中文逐字分词） |
| `app/tool/schema_validator.py` | JSON Schema 参数校验 + 详细错误反馈 |
| `app/tool/search.py` | tool_search 执行器 |
| `app/tool/proxy_executor.py` | tool_executor 代理执行器 |
| `app/tool/definitions.py` | tool_search / tool_executor 的 ToolDef |

**Phase 2: 系统集成**

| 修改文件 | 变更 |
|---|---|
| `app/skill/service.py` | 新增 `get_skill_summaries()` |
| `app/api/chat.py` | system 组装改为固定结构（基础提示 + 工具目录 + skill 摘要） |
| `app/main.py` | 注册 tool_search / tool_executor、创建 ToolIndex、添加权限规则 |

**迭代 B: MCP 接入**

| 新增文件 | 说明 |
|---|---|
| `app/mcp/__init__.py` | 模块导出 |
| `app/mcp/models.py` | 配置模型（MCPServerConfig, MCPConfig, MCPServerState） |
| `app/mcp/client.py` | MCP 客户端封装（connect, discover, call_tool） |
| `app/mcp/service.py` | MCP 服务（生命周期管理 + 工具注册/路由） |

MCP 支持 stdio（子进程）和 streamable-http（远程 HTTP）两种传输。
配置方式：`config.yaml` 中添加 `mcp.servers` 即可。

**权限规则**：
- `tool_search` → ALLOW（只读搜索）
- `tool_executor` → REQUIRE_APPROVAL（代理执行默认需审批）
- `system.execute_dynamic` → REQUIRE_APPROVAL（已有规则）

**缓存效果**：tools/system 完全固定，messages append-only。已有消息 100% 缓存命中。

**设计文档**：`docs/progressive-disclosure-design-v2.md`

**LLM 执行度测试（L3）**：

| 测试 | LLM 行为 | 结果 |
|---|---|---|
| echo 发现+调用 | tool_search("echo") → tool_executor(text="hello world") | ✅ |
| add integer 参数 | tool_search("add") → tool_executor(a=123, b=456) → 579 | ✅ |
| greet enum 参数 | tool_search("greet") → tool_executor(name="Alice", style="casual") | ✅ |
| 错误自恢复 | tool_executor({}) → 缺参数错误 → tool_executor(name="Test") → 成功 | ✅ |
| 连续多工具 | echo + add + greet 各自 search → execute，6 步完成 | ✅ |

**修复的 Bug（1 个）**：

| # | 问题 | 修复 |
|---|---|---|
| 1 | MCP 连接时先标记 CONNECTED 再注册工具，导致 race condition | 先注册工具再标记 CONNECTED |

**测试新增**：+110 个（ToolIndex 16 + SchemaValidator 26 + ToolSearch 9 + ProxyExecutor 15 + SkillSummaries 4 + MCPService 16 + MCP 集成 18 + LLM 执行度 5 + 其他 1）

**验证**：后端 447 测试全部通过。

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
| 会话标题自动生成 | P2 | 当前用消息前 20 字，无自动摘要 |
| 更多工具 | P2 | web_search、python_execute |
| skills.sh 在线安装 | P2 | 需接入外部服务 + 后端执行 npx 的接口 |
| Workflow 模块 | 长期 | 多步骤任务流程、状态恢复 |
| 分布式执行 | 长期 | Temporal 集成 |

## 下一步计划

### 短期

1. **会话标题自动生成**
   - 首轮对话后用 LLM 摘要生成标题

2. **会话标题自动生成**
   - 首轮对话后用 LLM 摘要生成标题

### 中期

3. **更多 Tools**
   - web_search
   - python_execute

4. **会话标题自动生成**

5. **skills.sh 在线安装**

### 长期

6. **Workflow 模块**
7. **分布式执行（Temporal）**

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
