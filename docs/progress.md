# Shorekeeper 开发进度

> 最后更新：2026-08-06

## 架构完成度

```
层级                    模块                状态        提交
─────────────────────────────────────────────────────────────
UI (Vue)               聊天界面             ✅ 完成      8660dff
UI (Vue)               Skills/记忆管理      ❌ 未开始    -
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
Business: Skill        全部                ✅ 完成      b5776f3
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
```

## 已验证的端到端流程

| 测试 | 状态 | 说明 |
|---|---|---|
| 基本对话 | ✅ | LLM 正常回复 |
| 流式对话 (SSE) | ✅ | 文本实时增量输出 |
| Memory write_memory | ✅ | 写入长期记忆 |
| Memory search_memory | ✅ | 跨会话记忆召回 |
| Permission 拦截 | ✅ | bash_execute 触发 REQUIRE_APPROVAL |
| Approval 审批通过 | ✅ | 创建审批 → 允许 → 执行 → 回复 |
| Approval 审批拒绝 | ✅ | 拒绝 → 工具不执行 → AI 说明被拒 |
| Run 暂停/恢复 | ✅ | WAITING → Resume → COMPLETED |
| 多轮上下文 | ✅ | 同一会话上下文连贯 |
| 停止生成 | ✅ | run 正确取消 |
| 重新生成 | ✅ | 重新生成指定消息 |
| 会话管理 | ✅ | 新建 / 切换 / 删除（前后端一致） |

## 待解决问题

| 问题 | 优先级 | 说明 |
|---|---|---|
| Skills/记忆管理页面 | P0 | 后端 API 就绪，前端页面未实现 |
| 会话删除确认框 | P1 | 原生 confirm() 不符合 KunUI 风格 |
| search_memory 搜索质量 | P1 | LIKE AND 语义，整句查询命中率低 |
| 审批过期清理 | P1 | expire_stale 存在但未定时调用 |
| 取消的 run 重新生成 | P1 | 空消息无重新生成按钮 |
| 会话标题自动生成 | P2 | 当前用消息前 20 字 |

## 下一步计划

### 短期（当前迭代）

1. **前端管理页面**
   - Skills 管理页
   - 记忆管理页

2. **P1 体验优化**
   - KunUI 确认框替换原生 confirm
   - search_memory 搜索改进（OR 语义 + 中文滑动窗口）
   - 审批过期定时清理
   - 取消消息可重新生成

### 中期

3. **更多 Tools**
   - web_search
   - python_execute

4. **会话标题自动生成**

### 长期

5. **Workflow 模块**
6. **分布式执行（Temporal）**

## 提交历史

| 提交 | 日期 | 内容 |
|---|---|---|
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
