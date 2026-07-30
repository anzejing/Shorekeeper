# Architecture

> 本文档定义项目架构规范。所有人和 AI 都必须遵守。本文档不是介绍项目，而是**约束项目**。

---

## 1. Design Philosophy

本项目不是聊天机器人，而是一个长期维护的 **AI Assistant Platform**。

### 核心原则

1. **Business Logic 与 Agent Runtime 解耦**
   - 业务逻辑独立于具体的 AI Runtime 实现
   - Runtime 只是业务层的执行引擎，不包含业务判断

2. **所有能力均可替换**
   - 任何模块都应设计为可插拔
   - 通过接口通信，不依赖具体实现

3. **所有状态均可恢复**
   - 任何中断后都能从断点恢复
   - 不丢失上下文、不丢失执行进度

4. **模块之间只能通过接口通信**
   - 模块内部实现可以任意变更
   - 模块间通过明确定义的接口交互

5. **禁止跨层调用**
   - 严格遵循依赖层级
   - 上层可调用下层，下层绝不能反向依赖上层

---

## 2. Overall Architecture

```
Vue (UI)
  ↓
FastAPI (API Layer)
  ↓
Assistant Service
  ↓
┌──────────────────────────────────────┐
│                                      │
│  Memory          Skill               │
│                                      │
│  Permission                         │
│                                      │
│  (Workflow — 预留，暂不实现)          │
│                                      │
└──────────────────────────────────────┘
  ↓
Runtime Adapter
  ↓
LiteLLM
  ↓
LLM Provider (Anthropic / OpenAI / Google / ...)
```

### 各层职责与边界

#### UI 层 (Vue + KunUI + Tailwind CSS)
- **负责**：界面渲染、用户交互、数据展示
- **技术栈**：Vue 3.5+ / TypeScript / Vite / Tailwind CSS v4 / KunUI (`@kungal/ui-vue`)
- **不负责**：业务逻辑判断、数据变换、直接调用 Runtime

#### API 层 (FastAPI)
- **负责**：HTTP 接口定义、请求路由、参数校验、响应格式化
- **不负责**：业务逻辑、数据持久化、Agent 执行

#### Assistant Service
- **负责**：协调各模块、编排业务流程、管理会话生命周期
- **不负责**：具体模块的内部实现、直接的 LLM 调用

#### Runtime Adapter
- **负责**：统一 Agent 执行接口、屏蔽不同 Runtime 差异、Agent Loop、Tool Calling、Streaming、Retry、Context 管理
- **不负责**：Memory、Skill、Permission、Workflow、数据库查询、业务判断

#### LiteLLM
- **负责**：多 Provider LLM 统一调用、消息格式转换、Token 计算、重试、错误处理
- **不负责**：Agent Loop、Tool 实现、Memory 访问、业务流程控制

---

## 3. Module Responsibilities

### Memory

**职责**：
- 短期记忆（当前会话上下文）
- 长期记忆（跨会话用户偏好、历史信息）
- RAG（检索增强生成）
- 对话历史的存储、检索、摘要

**禁止**：
- 不能直接调用 Runtime
- 不能操作 UI
- 不能判断业务逻辑

---

### Skill

**职责**：
- Skill 的注册与管理
- Prompt 注入
- Tool Chain 编排
- Skill 可组合：多个 Skill 可拼接为更复杂的能力

**禁止**：
- 不能管理用户
- 不能访问 Runtime 内部状态
- 不能直接操作 Memory

---

### Permission

**职责**：
- Tool 调用权限控制
- 数据访问权限控制
- Skill 使用权限控制
- 敏感操作的确认机制

**禁止**：
- 不能包含业务逻辑
- 不能定义 Skill 或 Tool 的行为

---

### Runtime Adapter

**职责**：
- 统一 Tool Calling 接口
- Streaming 转发
- Session 维护
- 将 Runtime 的 Tool 调用请求路由到 Business Layer 注册的 Tool

**禁止**：
- 不能查询数据库
- 不能判断业务
- 不能直接访问 Memory
- 不能直接操作 Skill

---

### Workflow（预留）

**职责**（将来实现时）：
- 多步骤任务流程定义与执行
- 条件分支、循环、暂停等待人工介入
- 状态可恢复：中断后从断点继续

**禁止**（将来实现时）：
- 不能绕过 Permission
- 不能直接访问 Runtime 内部状态

---

## 4. Dependency Rules

### 依赖层级

```
UI
  ↓
API
  ↓
Assistant
  ↓
Business Layer（Memory / Skill / Permission / Workflow）
  ↓
Runtime Adapter
  ↓
Runtime
```

### 规则

**只能向下依赖，绝不能反向。**

| 禁止 |
|---|
| Runtime import Memory |
| Skill import UI |
| Runtime Adapter import Business Layer |
| Memory import Assistant |

### Runtime 如何获取 Memory 数据

Runtime 不能直接访问 Memory。流程如下：

1. Memory 的访问能力被封装为 Tool（如 `read_memory`、`write_memory`、`search_memory`）
2. Tool 在 Business Layer 注册
3. Runtime 通过 Tool Calling 机制调用 Tool
4. Tool 内部访问 Memory，返回结果给 Runtime

```
Runtime 只知 Tool 接口，不知 Memory 存在
```

---

## 5. Data Flow

### 标准数据流

```
User
  ↓
Assistant
  ↓
Memory（检索上下文）
  ↓
Prompt Builder（组装 Prompt）
  ↓
Runtime（执行 Agent Loop）
  ↓
Tool（Runtime 通过 Tool Calling 调用）
  ↓
Assistant（处理 Tool 返回结果）
  ↓
UI（展示最终回复）
```

### 要求

- 所有功能的数据流必须符合此路径
- 不能跳过中间环节
- 所有改动必须追踪数据流和状态变化
- 必须确保整个数据流和状态流符合预期，而非仅关注单一状态改变

---

## 6. Tool Architecture

### Tool 调用机制

所有 Tool 必须经过以下三步：

```
Registry → Permission → Execute
```

| 步骤 | 说明 |
|---|---|
| **Registry** | Tool 必须注册到统一的 Tool 注册中心，不能散落在各处 |
| **Permission** | 调用前必须经过权限检查 |
| **Execute** | 权限通过后才执行 Tool 逻辑 |

### 禁止

- Runtime 不能直接 import Tool
- Runtime 不能绕过 Registry 直接调用 Tool
- Runtime 不能跳过 Permission 检查

---

## 7. Coding Principles

| 原则 | 说明 |
|---|---|
| 一个文件，一个职责 | 每个文件只做一件事 |
| 一个模块，一个入口 | 每个模块有且仅有一个对外入口 |
| 不要 Utility God Class | 不创建万能工具类 |
| 不要 3000 行 | 单个文件不能过长 |

---

## 8. PR Checklist

所有 Merge 前必须回答：

| 检查项 | 说明 |
|---|---|
| 影响哪些模块？ | 列出所有受影响的模块 |
| 新增哪些依赖？ | 列出所有新增的模块间依赖 |
| 是否违反架构？ | 对照本文档逐条检查 |
| 数据流是否变化？ | 如有变化，给出变化后的完整数据流 |
| 状态变化是否追踪？ | 所有状态变化是否可追踪、可恢复 |
