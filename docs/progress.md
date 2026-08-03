# Shorekeeper 开发进度

> 最后更新：2026-08-03

## 架构完成度

```
层级                    模块                状态        提交
─────────────────────────────────────────────────────────────
UI (Vue)               -                   ❌ 未开始    -
API                    chat                ✅ 完成      d8c0ea9
API                    memory              ✅ 完成      0860fd7
API                    skill               ✅ 完成      b5776f3
API                    permission          ✅ 完成      b7e04f3
API                    approval            ✅ 完成      b7e04f3
API                    config              ✅ 完成      (早期)
API                    runtime             ✅ 完成      (早期)
─────────────────────────────────────────────────────────────
Assistant Service      最小版 (chat API)   ⚠️ 临时      d8c0ea9
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
| Memory write_memory | ✅ | 写入长期记忆 |
| Memory read_memory | ✅ | 跨会话记忆召回 |
| Memory search_memory | ✅ | 搜索记忆和历史 |
| Permission 拦截 | ✅ | bash_execute 触发 REQUIRE_APPROVAL |
| Approval 审批 | ✅ | 创建审批 → 审批通过 |
| Run 暂停/恢复 | ✅ | WAITING → Resume → COMPLETED |

## 待解决问题

| 问题 | 优先级 | 说明 |
|---|---|---|
| LLM function calling 兼容性 | P0 | mimo-v2.5 返回文本而非结构化 tool_call，需换模型或适配 |
| Assistant Service 完善 | P1 | 当前 chat API 是最小版，需要流式、多轮上下文管理 |
| Permission 默认规则 | P1 | 当前 memory 工具默认 ALLOW，需要根据实际场景调整 |
| 审批超时处理 | P1 | ApprovalManager 有 expire_stale 但未定时调用 |

## 下一步计划

### 短期（当前迭代）

1. **换一个支持 function calling 的 LLM 做端到端测试**
   - 验证 Permission + Tool + Approval 全链路
   - 确认工具调用格式正确

2. **完善 Assistant Service**
   - 流式响应（SSE）
   - 多轮上下文管理
   - 会话标题自动生成

### 中期

3. **前端 UI**
   - 聊天界面
   - 审批对话框
   - 记忆/Skill/权限管理页面

4. **更多 Tools**
   - web_search
   - python_execute

### 长期

5. **Workflow 模块**
6. **分布式执行（Temporal）**

## 提交历史

| 提交 | 日期 | 内容 |
|---|---|---|
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
