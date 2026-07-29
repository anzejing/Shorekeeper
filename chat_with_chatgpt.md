可以，而且我建议这两个文档不要写成"提示词"，而是写成**项目规范（Project Standards）**。

以后无论是 Pi、Claude Code、Codex、OpenHands 还是 GPT，都遵守同一套规范。

我建议直接放到项目根目录：

```text
docs/

    architecture.md          # 项目架构规范（人和AI都必须遵守）

    ai-development.md        # AI开发流程规范
```

这两个文档甚至比 `AGENTS.md` 更重要。

---

# 第一份：《architecture.md》

这份不是介绍项目，而是**约束项目**。

我建议按照下面这种结构。

---

# 1. Design Philosophy（设计原则）

例如：

> 本项目不是聊天机器人，而是长期维护的 AI Assistant Platform。

明确几个原则：

```
Business Logic 与 Agent Runtime 解耦

所有能力均可替换

所有状态均可恢复

模块之间只能通过接口通信

禁止跨层调用
```

这是最高原则。

以后 AI 不能违反。

---

# 2. Overall Architecture

画整个架构。

例如：

```text
Vue

↓

FastAPI

↓

Assistant Service

↓

────────────────────────

Memory

Workflow

Knowledge

Skill

Permission

Task

────────────────────────

Runtime Adapter

↓

Pi Runtime
Claude Runtime
OpenAI Runtime

↓

LLM
```

并且说明：

谁负责什么。

谁不能负责什么。

例如：

```
Runtime

负责：

Agent Loop

Tool Calling

Streaming

Retry

Context

不负责：

Memory

Workflow

Skill

Permission
```

---

# 3. Module Responsibilities

例如：

## Memory

职责：

```
长期记忆

短期记忆

RAG

Conversation

```

禁止：

```
不能直接调用 Runtime

不能操作 UI

```

---

## Runtime

职责：

```
执行 Agent

调用 Tool

维护 Session
```

禁止：

```
不能查询数据库

不能判断业务

不能操作 Workflow
```

---

## Skill

职责：

```
Prompt

Workflow

Tool Chain
```

禁止：

```
不能管理用户

不能访问 Runtime 内部状态
```

---

这样 AI 就不会：

把所有代码写 Runtime。

---

# 4. Dependency Rules

这是我认为最重要的一章。

例如：

```
UI

↓

API

↓

Assistant

↓

Business Layer

↓

Runtime Adapter

↓

Runtime
```

只能：

向下依赖。

绝不能：

反向。

例如：

禁止：

```
Runtime import Memory

Skill import UI

Workflow import Runtime Internal

```

---

# 5. Data Flow

例如：

```
User

↓

Assistant

↓

Memory

↓

Prompt Builder

↓

Runtime

↓

Tool

↓

Assistant

↓

UI
```

所有功能：

必须符合。

---

# 6. Tool Architecture

规定：

所有 Tool：

必须：

```
Registry

↓

Permission

↓

Execute
```

不能：

```
Runtime

直接 import Tool
```

---

# 7. Coding Principles

例如：

```
一个文件

一个职责

一个模块

一个入口
```

不要：

Utility God Class。

不要：

3000 行。

---

# 8. PR Checklist

Merge 前：

必须回答：

```
影响哪些模块？

新增哪些依赖？

是否违反架构？

数据流是否变化？

```

---

我觉得这一份应该控制在 **20~30 页**。

以后 AI 每次都必须先读。

---

# 第二份：《ai-development.md》

这一份更重要。

它不是代码规范。

而是：

AI 工作规范。

---

# 1. AI Role

第一句话：

```
AI 是项目工程师。

不是架构师。

不是产品经理。

```

非常重要。

AI：

不能自己改架构。

---

# 2. Development Workflow

严格规定：

永远：

```
Requirement

↓

Specification

↓

Architecture Review

↓

Implementation

↓

Self Review

↓

Test

↓

Human Review

↓

Merge
```

禁止：

```
Requirement

↓

Code
```

---

# 3. Before Coding

AI：

必须：

输出：

```
功能理解

数据流

影响模块

风险

测试方案
```

没有。

不能：

写代码。

---

# 4. Coding Rules

例如：

每个 PR：

```
<300 行
```

每个功能：

```
一次只做一件事
```

禁止：

```
顺便优化

顺便重构

顺便修 Bug
```

---

# 5. Self Review

代码完成：

必须：

输出：

```
Architecture Review

Data Flow Review

Dependency Review

Risk Review
```

例如：

```
新增：

ModelStore

原因：

统一模型状态

影响：

Runtime

UI

API

```

---

# 6. Testing Rules

不要：

```
写测试
↓

结束
```

而是：

```
Unit Test

↓

Integration

↓

Playwright

↓

Manual Checklist
```

---

例如：

Playwright：

必须：

证明：

```
UI

↓

API

↓

Runtime

↓

真正改变
```

而不是：

文字改变。

---

# 7. Fake Feature Detection

这一章我一定会写。

例如：

AI：

完成：

必须回答：

```
有没有假的 UI？

有没有假的 API？

有没有 Mock？

有没有 Placeholder？

有没有 TODO？

有没有未真正连接 Runtime？
```

回答：

YES。

不能 Merge。

---

# 8. Review Checklist

例如：

Reviewer：

必须检查：

```
有没有重复实现？

有没有违反 Architecture？

有没有新增耦合？

有没有不可维护代码？

有没有绕过已有模块？
```

---

# 9. Human Review

规定：

人：

只 Review：

```
Architecture

Dependency

Interface

Naming

Risk
```

不要：

一个字一个字。

看代码。

---

# 10. Merge Criteria

例如：

满足：

```
Specification

√

Architecture

√

Review

√

Test

√

Manual

√

```

才能 Merge。

---

# 我还有一个建议（我觉得对你的项目价值更大）

结合我们这几个月一直聊的内容（Pi、OpenClaw、Hermes、Skill、Memory、Workflow 等），我觉得你的项目已经不是一个普通 Web 项目了，而是在做一个**长期演进的 AI Assistant 平台**。

所以我实际上建议你准备 **四份长期维护的核心文档**，而不是两份：

```text
docs/

├── architecture.md
│     系统架构、模块边界、依赖规则
│
├── ai-development.md
│     AI 开发流程、Review、测试规范
│
├── product-spec.md
│     功能规格（每个功能的行为、数据流、验收标准）
│
└── engineering-principles.md
      整个项目的长期设计哲学，例如：
      - Runtime 可替换
      - Business 与 Runtime 解耦
      - Skill 可组合
      - Workflow 可恢复
      - Event First
      - Small PR
      - Architecture Before Code
```

我认为这四份文档会成为你的项目最有价值的资产。以后 AI 换了、模型升级了、SDK 更换了，它们依然适用，而 AI 生成的代码反而会不断被替换。
