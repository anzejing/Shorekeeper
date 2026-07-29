# Engineering Principles

> 本文档定义项目的长期设计哲学。这些原则在 AI 更换、模型升级、SDK 更换后依然适用。

---

## 1. Runtime 可替换

- Runtime 是执行引擎，不承载业务逻辑
- 通过 Runtime Adapter 抽象统一接口
- Pi、Claude、OpenAI 等 Runtime 可互相替换
- 替换 Runtime 不应影响上层业务

---

## 2. Business 与 Runtime 解耦

- 业务逻辑（Memory、Skill、Permission、Workflow）不依赖 Runtime 实现
- Runtime 不包含业务判断
- Business Layer 通过 Tool 向 Runtime 暴露能力，而非让 Runtime 直接访问
- 始终保持：Business 在上，Runtime 在下

---

## 3. Skill 可组合

- 每个 Skill 只做一件事
- 多个 Skill 可以像积木一样拼接为更复杂的能力
- Skill 之间互不感知，通过声明式编排组合
- 类比：Unix 管道 —— 每个工具单一职责，可串联使用

---

## 4. Workflow 可恢复

- 所有工作流中断后能从断点恢复
- 不丢失上下文、不丢失执行进度
- 状态持久化是 Workflow 的一等公民

---

## 5. Event First

- 模块间通信优先使用事件
- 发送方不关心谁来消费
- 降低耦合，提高扩展性

---

## 6. Small PR

- 每个 PR 变更量 < 300 行
- 一次只做一件事
- 便于审查、便于回滚、便于定位问题

---

## 7. Architecture Before Code

- 先确定架构，再写代码
- 每段代码都应对照 architecture.md 验证
- 架构违规的代码不能 Merge
- 宁可少写，不要乱写
