# AI Development

> 本文档定义 AI 的开发工作规范。不是代码规范，而是 **AI 工作规范**。

---

## 1. AI Role

> **AI 是项目工程师，不是架构师，不是产品经理。**

- AI 执行开发任务，不自行决定架构
- **所有涉及架构层面的决策，必须与用户确认后方可执行**
- AI 不能自行新增模块、修改依赖关系、改变数据流

---

## 2. Development Workflow

### 标准流程

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

### 禁止

```
Requirement → Code  （禁止跳步）
```

---

## 3. Before Coding

在写任何代码之前，AI 必须先输出以下内容并获得用户确认：

| 输出项 | 说明 |
|---|---|
| **功能理解** | 用自己的话描述要做什么功能 |
| **数据流** | 画出该功能的数据流路径（符合 architecture.md 第 5 节） |
| **影响模块** | 列出所有受影响的模块 |
| **风险** | 指出潜在的风险和边界情况 |
| **测试方案** | 说明如何测试该功能 |

**没有以上输出，不能开始写代码。**

---

## 3.1 渐进式开发流程

项目采用**渐进式开发**模式：不需要在项目初期定义所有模块的接口和数据模型，而是在每个模块开发前再定义该模块的详细设计。

### 开发流程

```
选择功能模块
    ↓
输出开发准备清单（Development Readiness Checklist）
    ↓
用户确认
    ↓
开始开发
    ↓
完成并提交
    ↓
选择下一个模块
```

### 优势

1. **降低前期成本**：不需要一次性定义所有细节
2. **渐进明确**：随着开发推进，设计逐步清晰
3. **快速反馈**：每个模块完成后都能获得反馈
4. **灵活调整**：可以根据前一个模块的经验调整后续设计

---

## 3.2 开发准备清单（Development Readiness Checklist）

每个模块开发前，AI 必须输出以下清单并获得用户确认：

### 清单模板

```markdown
# [功能名称] 开发准备清单

## 1. 功能理解
（从 product-spec.md 中复制功能描述，用自己的话复述）

## 2. 数据流
（从 product-spec.md 中复制，确保符合 architecture.md 第 5 节）

## 3. 影响模块
（列出所有受影响的模块，包括新增和修改的模块）

## 4. API 接口定义

### 接口1：[接口名称]
- **路径**：METHOD /api/xxx
- **描述**：xxx
- **请求参数**：
```typescript
interface Request {
  // 定义请求参数
}
```
- **响应数据**：
```typescript
interface Response {
  // 定义响应数据
}
```
- **错误码**：
  - 400：参数错误
  - 404：资源不存在
  - 500：服务器错误

（重复以上格式定义所有接口）

## 5. 数据模型

```typescript
// 定义该模块涉及的所有数据模型
interface ModelName {
  field: type;
}
```

## 6. 风险和边界情况

| 风险 | 说明 | 处理策略 |
|------|------|----------|
| 风险1 | xxx | xxx |
| 风险2 | xxx | xxx |

## 7. 测试方案

### 单元测试
- 测试点1：xxx
- 测试点2：xxx

### 集成测试
- 测试场景1：xxx

### 端到端测试
- 用户流程：xxx

## 8. 确认

- [ ] 用户已确认以上内容
- [ ] 可以开始开发
```

### 清单要求

| 要求 | 说明 |
|------|------|
| **完整性** | 所有字段都必须填写，不能留空 |
| **具体性** | 接口和数据模型必须定义到字段级别 |
| **可测试** | 测试方案必须具体到可执行的测试用例 |
| **可追溯** | 每个风险都必须有对应的处理策略 |

### 确认机制

1. AI 输出开发准备清单
2. 用户审阅并确认（可以提出修改意见）
3. AI 根据反馈修改
4. 用户最终确认
5. AI 开始开发

**没有用户确认，不能开始写代码。**

---

## 3.3 模块开发顺序

模块开发顺序由用户决定，建议按以下优先级：

| 优先级 | 模块 | 说明 |
|--------|------|------|
| P0 | 配置管理 | 基础设施，其他模块依赖 |
| P0 | 会话管理 | 核心功能 |
| P0 | 对话系统 | 核心功能 |
| P1 | Skill 管理 | 重要功能 |
| P1 | Memory 管理 | 重要功能 |
| P1 | 工具调用 | 重要功能 |

**注意**：用户可以调整顺序，AI 不能自行决定开发顺序。

---

## 4. Coding Rules

| 规则 | 说明 |
|---|---|
| 每个 PR < 300 行 | 每个 Pull Request 的变更不超过 300 行 |
| 一次只做一件事 | 一个 PR 只完成一个明确的功能或修复 |
| 禁止顺便优化 | 不能在功能 PR 中附带无关的优化 |
| 禁止顺便重构 | 不能在功能 PR 中附带无关的重构 |
| 禁止顺便修 Bug | 无关的 Bug 修复必须单独 PR |

---

## 5. Self Review

代码完成后，AI 必须先自审，输出以下内容：

| 审查项 | 说明 |
|---|---|
| **Architecture Review** | 是否违反 architecture.md 中的任何规范？ |
| **Data Flow Review** | 数据流是否正确？是否跳过了中间环节？ |
| **Dependency Review** | 依赖关系是否正确？是否出现了反向依赖？ |
| **Risk Review** | 有什么风险？有哪些边界情况未覆盖？ |

自审未通过，不能进入 Test 阶段。

---

## 6. Testing Rules

### 测试流程

```
Unit Test
  ↓
Integration Test
  ↓
Playwright（端到端测试）
  ↓
Manual Checklist
```

### Playwright 要求

Playwright 测试必须能证明：

- UI → API → Runtime 真正打通
- 不是仅文字改变
- 不是假的数据流转

---

## 7. Fake Feature Detection

代码完成后，AI 必须回答以下问题：

| 检查项 |
|---|
| 有没有假的 UI？（只画界面但不连接后端） |
| 有没有假的 API？（返回 Mock 数据而不真正执行） |
| 有没有 Mock？（使用 Mock 替代真实模块） |
| 有没有 Placeholder？（写了占位符但未实现） |
| 有没有 TODO？（标记了 TODO 但未完成） |
| 有没有未真正连接 Runtime？（绕过了 Runtime 直接返回假回复） |

**以上任意一项回答 YES，不能 Merge。**

---

## 8. Review Checklist（Reviewer 检查项）

Reviewer 审查时必须检查：

| 检查项 | 说明 |
|---|---|
| 有没有重复实现？ | 是否已有模块提供相同能力 |
| 有没有违反 Architecture？ | 对照 architecture.md 逐条检查 |
| 有没有新增耦合？ | 模块间是否产生了不必要的依赖 |
| 有没有不可维护代码？ | 是否存在难以理解和修改的代码 |
| 有没有绕过已有模块？ | 是否绕过了 Memory/Skill/Permission 等已有模块 |

---

## 9. Human Review

人的审查范围：

| 审查 | 不审查 |
|---|---|
| Architecture | 逐行代码 |
| Dependency | 代码风格细节 |
| Interface | 实现细节 |
| Naming | |
| Risk | |

---

## 10. Merge Criteria

全部满足才能 Merge：

| 条件 | 状态 |
|---|---|
| Specification 已确认 | ☐ |
| Architecture 审查通过 | ☐ |
| Self Review 通过 | ☐ |
| Test 全部通过 | ☐ |
| Manual Checklist 通过 | ☐ |
| Fake Feature Detection 通过 | ☐ |
| Human Review 通过 | ☐ |
