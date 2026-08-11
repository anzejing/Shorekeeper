# Product Specification

> 本文档定义项目各功能的行为、数据流与验收标准。从用户视角描述"能做什么，系统应该有什么表现"。
>
> 按**功能域（Feature Area）**分层组织，每个功能域下包含具体功能。按开发优先级逐步补充。

---

## 功能域总览

| 编号 | 功能域 | 状态 | 优先级 |
|---|---|---|---|
| 1 | 应用外壳 | ✅ 已实现 | P0 |
| 2 | 对话系统 | ✅ 已实现（流式/审批/多轮） | P0 |
| 3 | Skill 管理 | ❌ 未实现（后端 API 就绪） | P1 |
| 4 | Memory 管理 | ❌ 未实现（后端 API 就绪） | P1 |
| 5 | 配置管理 | ✅ 已实现（Runtime 段已废弃，见 5.6） | P0 |
| 5.6 | 模型管理 | 🚧 开发中（多 Provider/Model、models.dev 目录、全局切换） | P0 |
| 6 | 会话管理 | ✅ 已实现 | P0 |
| 7 | 工具调用 | ✅ 已实现（卡片 + 审批确认） | P1 |

> 状态最后更新：2026-08-06。详见 `progress.md` 开发记录。

---

## 1. 应用外壳

### 1.1 左侧导航栏

**描述**：用户在所有页面都能看到一个统一的左侧导航栏，点击可跳转到对应页面。

**行为**：
- 用户打开任意页面 → 左侧显示导航栏，当前页面对应的导航项高亮
- 用户点击另一个导航项 → 页面跳转到目标页，导航项高亮切换
- 用户首次进入系统 → 默认跳转到第一个导航项对应的页面
- 窗口宽度过小时 → 导航栏自动折叠
- 当前页手动刷新 → 高亮状态保持

**数据流**：

```
用户点击 → Vue Router 切换 → 对应组件渲染
```

纯 UI 层，不经过 API / Assistant / Runtime。

**验收标准**：
- [ ] 侧边栏在所有页面保持一致的样式和位置
- [ ] 点击每个导航项都能跳转到正确的页面
- [ ] 当前页面对应的导航项视觉高亮
- [ ] 浏览器后退/前进，导航高亮正确跟随
- [ ] 窄屏下侧边栏正确折叠

**影响模块**：
- UI 层（Vue Router + 导航组件）

---

### 1.2 主内容区域

**描述**：导航栏右侧为主内容区域，根据当前路由显示对应的页面内容。

**行为**：
- 用户切换导航 → 主内容区域平滑切换
- 内容超出可视区域 → 显示滚动条
- 页面加载中 → 显示加载状态

**数据流**：

```
路由变化 → 组件渲染 → 内容展示
```

**验收标准**：
- [ ] 内容区域正确占据剩余空间
- [ ] 页面切换无闪烁
- [ ] 加载状态清晰可见

**影响模块**：
- UI 层（布局组件）

---

## 2. 对话系统

### 2.1 新建对话

**描述**：用户可以创建新的对话会话，开始与AI助手交流。

**行为**：
- 用户点击"新建对话"按钮 → 创建新会话 → 跳转到对话页面
- 用户输入问题 → 发送消息 → 显示AI回复
- 对话自动保存到会话列表

**数据流**：

```
用户输入 → Vue → FastAPI → Assistant Service → Session创建 → Runtime Adapter → Pi Runtime
                                              ↓
                                        会话持久化
```

**验收标准**：
- [ ] 点击新建按钮能创建新会话
- [ ] 新会话自动出现在会话列表
- [ ] 跳转到空的对话页面

**影响模块**：
- UI 层（对话组件）
- API 层（会话接口）
- Assistant Service（会话管理）

---

### 2.2 发送消息

**描述**：用户在对话页面输入文本并发送，等待AI回复。

**行为**：
- 用户在输入框输入文本 → 点击发送或按Enter → 消息显示在对话区域
- 消息发送后 → 输入框清空 → 显示"正在思考"状态
- AI回复开始 → 逐步显示回复内容（流式）
- AI回复完成 → 恢复输入状态

**数据流**：

```
用户输入 → Vue → FastAPI → Assistant Service → Memory（检索上下文）→ Prompt Builder → Runtime Adapter → Pi Runtime
                                              ↓
                                    SSE Stream ← Runtime Adapter
                                              ↓
                                        Vue（逐步渲染）
```

**验收标准**：
- [ ] 消息能成功发送
- [ ] 发送后显示加载状态
- [ ] AI回复能流式显示
- [ ] 回复完成后能继续对话

**影响模块**：
- UI 层（消息组件、输入组件）
- API 层（消息接口）
- Assistant Service（对话编排）
- Runtime Adapter（流式响应）
- Memory（上下文检索）

---

### 2.3 消息展示

**描述**：对话区域展示用户消息和AI回复，支持多种内容类型和样式。

**行为**：
- 用户消息右对齐，AI回复左对齐
- 支持多种消息块类型，每种类型使用不同样式：
  - **正文（Content）**：普通文本内容，支持Markdown渲染
  - **思考内容（Thinking）**：AI的思考过程，使用可折叠的灰色区块显示
  - **工具调用（Tool Call）**：工具执行命令，使用代码块样式显示工具名称和参数
  - **工具结果（Tool Result）**：工具返回结果，使用特殊样式显示执行状态和输出
  - **错误信息（Error）**：错误内容，使用红色边框和背景高亮显示
- 代码块支持语法高亮和复制按钮
- 长消息支持折叠/展开

**数据流**：

```
Runtime Adapter → Assistant Service → 消息解析 → 消息块分类 → Vue组件渲染
```

**消息块类型定义**：

```typescript
interface MessageBlock {
  id: string;
  type: 'content' | 'thinking' | 'tool_call' | 'tool_result' | 'error';
  content: string;
  metadata?: {
    toolName?: string;      // 工具名称
    toolArgs?: any;         // 工具参数
    status?: 'running' | 'success' | 'error';  // 执行状态
    duration?: number;      // 执行时长（ms）
  };
}
```

**验收标准**：
- [ ] 消息对齐方式正确
- [ ] 正文支持Markdown渲染
- [ ] 思考内容可折叠/展开
- [ ] 工具调用显示工具名称和参数
- [ ] 工具结果显示执行状态和输出
- [ ] 错误信息有视觉高亮
- [ ] 代码块有语法高亮
- [ ] 代码块有复制按钮

**影响模块**：
- UI 层（消息组件、消息块组件、Markdown渲染器）
- Assistant Service（消息解析）

---

### 2.4 多会话切换

**描述**：用户可以在多个对话会话之间切换，每个会话保持独立的上下文。

**行为**：
- 用户点击会话列表中的某个会话 → 切换到该会话 → 显示该会话的历史消息
- 切换会话时 → 当前会话自动保存
- 支持会话搜索和过滤

**数据流**：

```
用户点击 → Vue → FastAPI → Assistant Service → 加载会话历史 → Vue渲染
```

**验收标准**：
- [ ] 能成功切换会话
- [ ] 切换后显示正确的会话历史
- [ ] 切换时当前会话自动保存
- [ ] 支持会话搜索

**影响模块**：
- UI 层（会话列表组件）
- API 层（会话接口）
- Assistant Service（会话管理）

---

## 3. Skill 管理

### 3.1 Skill 列表

**描述**：用户可以查看系统中所有可用的Skill。

**行为**：
- 用户进入Skill管理页面 → 显示所有Skill列表
- 每个Skill显示名称、描述、状态（启用/禁用）、来源
- 支持Skill搜索和分类筛选

**数据流**：

```
用户访问 → Vue → FastAPI → Assistant Service → Skill模块 → 返回Skill列表 → Vue渲染
```

**验收标准**：
- [ ] 能正确显示所有Skill
- [ ] Skill信息完整（名称、描述、状态、来源）
- [ ] 支持搜索和筛选

**影响模块**：
- UI 层（Skill列表组件）
- API 层（Skill接口）
- Skill模块（Skill注册与管理）

---

### 3.2 Skill 启用/禁用

**描述**：用户可以启用或禁用特定的Skill。

**行为**：
- 用户点击Skill的开关 → 切换Skill状态 → 显示状态变更
- 禁用的Skill不会在对话中被调用
- 状态变更即时生效

**数据流**：

```
用户点击 → Vue → FastAPI → Assistant Service → Skill模块 → 更新状态 → 返回新状态 → Vue更新
```

**验收标准**：
- [ ] 能成功切换Skill状态
- [ ] 状态变更即时生效
- [ ] 禁用的Skill不会被调用

**影响模块**：
- UI 层（Skill开关组件）
- API 层（Skill接口）
- Skill模块（状态管理）

---

### 3.3 Skill 详情

**描述**：用户可以查看Skill的详细信息，包括其能力、配置和使用示例。

**行为**：
- 用户点击某个Skill → 显示Skill详情页
- 详情页包含：描述、支持的Tool列表、配置选项、使用示例
- 用户可以修改Skill配置

**数据流**：

```
用户点击 → Vue → FastAPI → Assistant Service → Skill模块 → 返回Skill详情 → Vue渲染
```

**验收标准**：
- [ ] 能正确显示Skill详情
- [ ] 信息完整且准确
- [ ] 配置修改能保存

**影响模块**：
- UI 层（Skill详情组件）
- API 层（Skill接口）
- Skill模块（配置管理）

---

### 3.4 从 skills.sh 安装 Skill

**描述**：用户可以从 [skills.sh](https://www.skills.sh) 目录安装社区Skill。

**行为**：
- 用户点击"从 skills.sh 安装"按钮 → 显示搜索界面
- 用户输入关键词或浏览分类 → 显示匹配的Skill列表
- 用户选择一个Skill → 显示Skill详情（描述、作者、安装数量）
- 用户点击"安装" → 调用 `npx skills add` 命令安装
- 安装完成后 → Skill出现在本地Skill列表中

**数据流**：

```
用户搜索 → Vue → skills.sh API → 返回搜索结果 → Vue渲染
用户选择 → Vue → FastAPI → 执行 npx skills add → 安装完成 → 刷新Skill列表
```

**支持的安装源**：

```bash
# GitHub shorthand
npx skills add owner/repo

# Full GitHub URL
npx skills add https://github.com/owner/repo

# Direct path to a skill
npx skills add https://github.com/owner/repo/tree/main/skills/skill-name

# GitLab URL
npx skills add https://gitlab.com/org/repo

# Any git URL
npx skills add git@github.com:owner/repo.git

# Local path
npx skills add ./my-local-skills
```

**验收标准**：
- [ ] 能搜索skills.sh目录
- [ ] 能显示Skill详情
- [ ] 能成功安装Skill
- [ ] 安装后Skill出现在列表中
- [ ] 支持多种安装源格式

**影响模块**：
- UI 层（搜索组件、安装组件）
- API 层（安装接口）
- Skill模块（安装逻辑）

---

### 3.5 选择性安装 Skill

**描述**：用户可以选择性地安装仓库中的特定Skill，而不是安装整个仓库。

**行为**：
- 用户输入仓库地址 → 显示仓库中的Skill列表
- 用户勾选要安装的Skill → 点击"安装选中"
- 系统调用 `npx skills add --skill <skill-name>` 安装选中的Skill
- 安装完成后 → 显示安装结果

**数据流**：

```
用户输入仓库 → Vue → FastAPI → 执行 npx skills add --list → 返回Skill列表 → Vue渲染
用户选择 → Vue → FastAPI → 执行 npx skills add --skill <name> → 安装完成 → 刷新列表
```

**CLI 命令**：

```bash
# 列出仓库中的Skill
npx skills add owner/repo --list

# 安装特定Skill
npx skills add owner/repo --skill skill-name-1 --skill skill-name-2

# 安装所有Skill
npx skills add owner/repo --skill '*'
```

**验收标准**：
- [ ] 能列出仓库中的Skill
- [ ] 能选择性安装Skill
- [ ] 安装后Skill出现在列表中
- [ ] 支持批量安装

**影响模块**：
- UI 层（选择组件、安装组件）
- API 层（安装接口）
- Skill模块（选择性安装逻辑）

---

### 3.6 Skill 更新与移除

**描述**：用户可以更新已安装的Skill或移除不需要的Skill。

**行为**：
- 用户点击"更新"按钮 → 检查并更新Skill到最新版本
- 用户点击"移除"按钮 → 二次确认 → 移除Skill
- 更新/移除后 → 刷新Skill列表

**数据流**：

```
用户操作 → Vue → FastAPI → 执行 npx skills update/remove → 操作完成 → 刷新列表
```

**CLI 命令**：

```bash
# 更新Skill
npx skills update skill-name

# 移除Skill
npx skills remove skill-name
```

**验收标准**：
- [ ] 能更新Skill到最新版本
- [ ] 移除前有二次确认
- [ ] 操作后列表正确更新

**影响模块**：
- UI 层（操作组件）
- API 层（更新/移除接口）
- Skill模块（更新/移除逻辑）

---

## 4. Memory 管理

### 4.1 对话历史

**描述**：用户可以查看所有对话历史记录。

**行为**：
- 用户进入Memory管理页面 → 显示对话历史列表
- 每条记录显示会话标题、时间、摘要
- 支持按时间、关键词搜索

**数据流**：

```
用户访问 → Vue → FastAPI → Assistant Service → Memory模块 → 返回历史列表 → Vue渲染
```

**验收标准**：
- [ ] 能正确显示对话历史
- [ ] 信息完整（标题、时间、摘要）
- [ ] 支持搜索功能

**影响模块**：
- UI 层（历史列表组件）
- API 层（Memory接口）
- Memory模块（历史存储）

---

### 4.2 长期记忆

**描述**：系统自动提取和存储用户的长期偏好和重要信息。

**行为**：
- 系统在对话中自动识别重要信息 → 存储为长期记忆
- 用户可以查看和编辑长期记忆
- 长期记忆在后续对话中自动作为上下文

**数据流**：

```
对话内容 → Memory模块 → 信息提取 → 长期记忆存储
用户查看 → Vue → FastAPI → Memory模块 → 返回记忆列表 → Vue渲染
```

**验收标准**：
- [ ] 系统能自动提取重要信息
- [ ] 长期记忆能正确存储
- [ ] 用户能查看和编辑
- [ ] 后续对话能自动使用

**影响模块**：
- API 层（Memory接口）
- Memory模块（信息提取、存储、检索）

---

### 4.3 记忆搜索

**描述**：用户可以搜索历史对话和长期记忆。

**行为**：
- 用户输入关键词 → 搜索对话历史和长期记忆 → 显示搜索结果
- 结果按相关性排序
- 点击结果可跳转到对应的对话

**数据流**：

```
用户输入 → Vue → FastAPI → Memory模块 → 搜索 → 返回结果 → Vue渲染
```

**验收标准**：
- [ ] 搜索功能正常工作
- [ ] 结果按相关性排序
- [ ] 点击结果能跳转

**影响模块**：
- UI 层（搜索组件）
- API 层（搜索接口）
- Memory模块（搜索功能）

---

## 5. 配置管理

### 5.1 统一配置系统

**描述**：所有项目中的可配置项都由统一的配置类管理，支持前端动态展示和自动重载。

**行为**：
- 所有配置项都从配置类中统一获取
- 配置项支持多种类型：字符串、数字、布尔、选择、数组、路径
- 配置项按分组组织，支持排序
- 敏感配置（如apiKey）在前端显示为 ***
- 配置变更后自动重载相关模块

**配置项接口定义**：

```typescript
interface ConfigItem {
  key: string;           // 配置键名，如 "server.port"
  label: string;         // 中文名，如 "服务器端口"
  description: string;   // 描述
  type: 'string' | 'number' | 'boolean' | 'select' | 'array' | 'path';
  default: any;          // 默认值
  options?: any[];       // 预设值列表（用于 select 类型）
  group: string;         // 分组，如 "服务器"、"日志"
  order: number;         // 排序
  required?: boolean;    // 是否必填
  secret?: boolean;      // 是否敏感信息（如 apiKey，前端显示为 ***）
}
```

**数据流**：

```
配置类注册 → FastAPI → 返回配置项列表 → Vue渲染配置界面
用户修改 → Vue → FastAPI → 配置类验证 → 保存配置 → 触发重载
```

**验收标准**：
- [ ] 所有配置项都从配置类获取
- [ ] 配置项类型正确
- [ ] 配置项按分组正确显示
- [ ] 敏感信息正确隐藏
- [ ] 配置变更能自动重载

**影响模块**：
- UI 层（配置组件）
- API 层（配置接口）
- 所有模块（配置读取）

---

### 5.2 配置分组

**描述**：配置项按功能分组，便于用户查找和管理。

**配置分组定义**：

| 分组 | 说明 | 示例配置项 |
|------|------|------------|
| 服务器 | 服务器相关配置 | 端口、主机、工作目录 |
| ~~Runtime~~ | ~~AI Runtime配置（已废弃，见 5.6 模型管理）~~ | ~~API Key、模型、温度参数~~ |
| 日志 | 日志配置 | 日志级别、日志路径、日志轮转 |
| 存储 | 存储配置 | 数据库路径、备份策略 |
| 安全 | 安全配置 | 会话超时、权限策略 |
| 界面 | 界面配置 | 主题、语言、字体大小 |

**验收标准**：
- [ ] 配置项按分组正确显示
- [ ] 分组支持折叠/展开
- [ ] 分组排序合理

**影响模块**：
- UI 层（分组组件）

---

### 5.3 配置验证

**描述**：配置项在保存前进行验证，确保配置值有效。

**行为**：
- 用户修改配置 → 前端验证格式 → 后端验证业务规则
- 验证失败 → 显示错误提示
- 验证成功 → 保存配置 → 触发重载

**验证规则**：
- 必填项检查
- 类型检查
- 范围检查（如端口号 1-65535）
- 格式检查（如路径格式）
- 依赖检查（如某些配置项依赖其他配置项）

**验收标准**：
- [ ] 必填项验证正确
- [ ] 类型验证正确
- [ ] 范围验证正确
- [ ] 错误提示清晰

**影响模块**：
- UI 层（验证逻辑）
- API 层（验证逻辑）
- 配置类（验证规则）

---

### 5.4 配置持久化

**描述**：配置项持久化存储，系统重启后配置不丢失。

**行为**：
- 配置保存到配置文件（如 YAML、JSON、TOML）
- 系统启动时加载配置文件
- 配置变更时更新配置文件
- 支持配置文件备份和恢复

**数据流**：

```
配置变更 → 配置类 → 写入配置文件 → 完成
系统启动 → 读取配置文件 → 配置类 → 加载配置
```

**验收标准**：
- [ ] 配置能正确持久化
- [ ] 系统重启后配置不丢失
- [ ] 支持配置备份和恢复

**影响模块**：
- 配置类（持久化逻辑）

---

### 5.5 配置重载

**描述**：配置变更后自动重载相关模块，无需重启系统。

**行为**：
- 配置变更 → 通知相关模块 → 模块重新加载配置
- 部分配置需要重启才能生效（如端口号）
- 部分配置即时生效（如日志级别）

**配置重载策略**：

| 配置类型 | 重载策略 | 说明 |
|----------|----------|------|
| 即时生效 | 自动重载 | 如日志级别、主题 |
| 需要重启 | 提示用户 | 如端口号、数据库路径 |
| 需要重新连接 | 提示重新连接 | 如 API Key、模型 |

**验收标准**：
- [ ] 即时生效配置能自动重载
- [ ] 需要重启的配置有提示
- [ ] 重载后功能正常

**影响模块**：
- 配置类（重载逻辑）
- 所有模块（配置监听）

---

### 5.6 模型管理（多 Provider / 多 Model）

> 详细设计见 [`docs/models-management.md`](models-management.md)。本小节为产品行为规格。

**描述**：替代旧 Runtime 单模型配置。用户可在独立「模型」页面（`/models`）配置多个 Provider 与多个模型，
聊天页支持全局模型切换与对话中热切换。

**行为**：
- Provider 类型：`openai`（官方）/ `openai_like`（兼容端点，需 base_url）/ `anthropic` / `gemini`
- Provider 与 api_key 存入 SQLite（响应/日志掩码）
- 每个 provider 下挂多模型；模型元数据（能力/上下文/定价）同步自 models.dev 目录
- 有 `/models` 端点的 provider 可手动同步，以真实模型列表覆盖 models.dev 不一致数据
- models.dev 目录：显示数据日期（last_updated 最大值）+ 手动同步按钮（ETag 304 增量判断）
- 全局当前模型可空可删除；为空时聊天发送提示「请先选择模型」
- 测试连接：Provider 表单与模型选择器均可选择/输入模型后点击测试
- 聊天页输入框左上方二级选择器（provider → model）切换当前模型
- 对话多轮后切换模型可继续对话（每轮 Run 从 memory 恢复完整上下文）
- Run 挂起（审批）期间切换模型，resume 仍使用该 Run 创建时的模型（model 持久化于 RunSnapshot.metadata）
- 模型元数据保留 cost 单价 + Run 记录 model_id/usage，为后续计量页面准备数据基础

**数据流**：

```
用户 → 模型页 → /api/models/* → ModelConfigService → SQLite
用户切换模型 → PUT /api/models/current
发送消息 → POST /api/chat/stream {model} → RunRequest.metadata
  → RunSnapshot.metadata 持久化 → run_loop → litellm（前缀含 provider）
```

**验收标准**：
- [ ] 模型页可增删改 4 种类型 provider，api_key 掩码显示
- [ ] provider 下可增删模型，元数据正确展示
- [ ] models.dev 目录同步成功，数据日期正确显示，ETag 未变返回 unchanged
- [ ] /models 端点同步成功，模型列表与 provider 实际一致
- [ ] 聊天页二级选择器切换全局模型，发送使用新模型
- [ ] 当前模型为空时发送聊天有明确提示
- [ ] 测试连接可用（选择/输入模型 → 测试 → 成功/失败反馈）
- [ ] 热切换：对话中途换模型继续对话上下文不丢；挂起恢复不串模型

**影响模块**：
- UI 层（ModelsView、模型选择器）
- API 层（models API、chat API）
- ModelConfig 模块（新增）
- Runtime Adapter（per-run model 持久化）
- Config 模块（移除 Runtime 段）

---

## 6. 会话管理

### 6.1 会话列表

**描述**：用户可以查看所有对话会话。

**行为**：
- 用户进入会话列表页面 → 显示所有会话
- 每个会话显示标题、最后更新时间、消息数量
- 支持按时间、关键词搜索

**数据流**：

```
用户访问 → Vue → FastAPI → Assistant Service → 返回会话列表 → Vue渲染
```

**验收标准**：
- [ ] 能正确显示所有会话
- [ ] 信息完整（标题、时间、消息数）
- [ ] 支持搜索功能

**影响模块**：
- UI 层（会话列表组件）
- API 层（会话接口）
- Assistant Service（会话管理）

---

### 6.2 会话操作

**描述**：用户可以对会话进行重命名、删除、归档等操作。

**行为**：
- 用户右键点击会话 → 显示操作菜单
- 支持操作：重命名、删除、归档、导出
- 删除操作需二次确认

**数据流**：

```
用户操作 → Vue → FastAPI → Assistant Service → 执行操作 → 返回结果 → Vue更新
```

**验收标准**：
- [ ] 所有操作都能正常执行
- [ ] 删除前有二次确认
- [ ] 操作后列表即时更新

**影响模块**：
- UI 层（会话操作组件）
- API 层（会话接口）
- Assistant Service（会话管理）

---

### 6.3 会话恢复

**描述**：用户可以恢复之前中断的会话。

**行为**：
- 用户点击某个会话 → 加载会话历史 → 恢复对话上下文
- 恢复后可以继续对话
- 支持从断点恢复（Workflow场景）

**数据流**：

```
用户点击 → Vue → FastAPI → Assistant Service → Memory模块 → 加载历史 → 恢复上下文 → Vue渲染
```

**验收标准**：
- [ ] 能成功恢复会话
- [ ] 历史消息正确显示
- [ ] 上下文正确恢复
- [ ] 可以继续对话

**影响模块**：
- UI 层（会话恢复组件）
- API 层（会话接口）
- Assistant Service（会话管理）
- Memory模块（上下文恢复）

---

## 7. 工具调用

### 7.1 工具调用可视化

**描述**：用户可以查看AI在对话中调用的工具和执行结果。

**行为**：
- AI调用工具时 → 在对话中显示工具调用卡片
- 卡片显示：工具名称、输入参数、执行状态、输出结果
- 支持折叠/展开详细信息

**数据流**：

```
Runtime Adapter（工具调用）→ Assistant Service → Vue（工具卡片渲染）
```

**验收标准**：
- [ ] 工具调用能正确显示
- [ ] 信息完整（名称、参数、状态、结果）
- [ ] 支持折叠/展开

**影响模块**：
- UI 层（工具卡片组件）
- Assistant Service（工具调用处理）
- Runtime Adapter（工具调用）

---

### 7.2 工具调用确认

**描述**：对于敏感工具，用户需要确认后才能执行。

**行为**：
- AI调用敏感工具 → 显示确认对话框
- 用户确认 → 执行工具
- 用户拒绝 → 跳过该工具调用

**数据流**：

```
Runtime Adapter（工具调用）→ Permission模块 → 需要确认 → Vue（确认对话框）
用户确认 → Vue → FastAPI → Assistant Service → Runtime Adapter → 执行工具
```

**验收标准**：
- [ ] 敏感工具有确认提示
- [ ] 确认后能正常执行
- [ ] 拒绝后能继续对话

**影响模块**：
- UI 层（确认对话框组件）
- API 层（确认接口）
- Permission模块（权限检查）
- Runtime Adapter（工具执行）

---

### 7.3 工具管理

**描述**：用户可以查看和管理系统中所有可用的工具。

**行为**：
- 用户进入工具管理页面 → 显示所有工具列表
- 每个工具显示名称、描述、权限要求
- 支持工具搜索和分类筛选

**数据流**：

```
用户访问 → Vue → FastAPI → Skill模块 → 返回工具列表 → Vue渲染
```

**验收标准**：
- [ ] 能正确显示所有工具
- [ ] 信息完整（名称、描述、权限）
- [ ] 支持搜索和筛选

**影响模块**：
- UI 层（工具列表组件）
- API 层（工具接口）
- Skill模块（工具管理）

---

## 附录：优先级说明

| 优先级 | 说明 | 包含功能 |
|--------|------|----------|
| P0 | 核心功能，MVP必须 | 应用外壳、对话系统、会话管理、配置管理 |
| P1 | 重要功能，第二阶段 | Skill管理、Memory管理、工具调用 |
| P2 | 增强功能，第三阶段 | 高级功能 |

---

## 附录：技术约束

1. **前端框架**：Vue 3.5+ + TypeScript + Vite
2. **UI 组件库**：KunUI (`@kungal/ui-vue`) — 跨框架无头 UI 组件库，53 个组件，Tailwind v4 原生
3. **CSS 框架**：Tailwind CSS v4 + `@kungal/ui-tokens`（KunUI 设计令牌）
4. **状态管理**：Pinia
5. **路由**：Vue Router
6. **后端**：FastAPI + Python
7. **通信**：HTTP API + SSE（Server-Sent Events）
8. **持久化**：SQLite（开发阶段）/ PostgreSQL（生产阶段）
9. **配置格式**：YAML 或 TOML
10. **Skill安装**：支持 skills.sh CLI

### KunUI 集成说明

本项目使用 **plain Vue (Vite)** 模式集成 KunUI，不依赖 Nuxt。

#### 安装依赖

```bash
pnpm add @kungal/ui-vue @kungal/ui-core @kungal/ui-tokens tailwindcss @tailwindcss/vite
```

#### 入口 CSS（`src/assets/main.css`）

```css
@import 'tailwindcss';
@import '@kungal/ui-tokens';
@import '@kungal/ui-vue/style.css';

@source '../../node_modules/@kungal/ui-vue';
@source '../../node_modules/@kungal/ui-core';
```

#### 入口 TS（`src/main.ts`）

```typescript
import { createApp } from 'vue'
import { KunUI, installKunUIConfig } from '@kungal/ui-vue'
import { createRouter, createWebHistory, RouterLink } from 'vue-router'
import App from './App.vue'
import './assets/main.css'

const app = createApp(App)
const router = createRouter({ history: createWebHistory(), routes: [/* ... */] })

app.use(router).use(KunUI)

installKunUIConfig(app, {
  linkComponent: RouterLink,
  navigate: (href) => router.push(href),
})

app.mount('#app')
```

#### Overlay Providers（在根组件挂载一次）

```vue
<template>
  <RouterView />
  <KunMessageProvider />
  <KunAlertProvider />
</template>
```

#### Dark Mode

切换 `<html>` 上的 `kun-dark-mode` class：

```typescript
document.documentElement.classList.toggle('kun-dark-mode', isDark)
```

#### 安全：HTML 净化

KunUI **不内置 HTML 净化**。所有用户输入的 HTML 内容在传入 `KunContent` 或 `useKunMessage(richText=true)` 之前，**必须**使用 DOMPurify 等工具净化。

#### 图标

KunUI 图标为内置 SVG 注册表，**不运行时请求外部 API**。使用 `registerKunIcon()` / `registerKunIcons()` 在启动时注册自定义图标。

---

## 附录：验收标准格式

每个功能的验收标准使用以下格式：
- [ ] 功能点1
- [ ] 功能点2
- [ ] ...

表示需要在实现后验证的功能点。
