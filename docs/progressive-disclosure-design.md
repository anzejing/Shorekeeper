# 渐进式披露 + 输入缓存命中 设计（已确认，待实施）

> 状态：**设计已确认**，实施待后续迭代。
> 日期：2026-08-07
> 关联：MCP 接入（迭代 B）、Skill/Tool 上下文管理

## 1. 背景与目标

接入 Agent Plugins 插件与未来的 MCP 后，工具数量会快速增长。当前实现（`chat.py` + `skill/service.py`）**全量注入**：

- 所有 enabled skill 的完整 prompt 全部拼进 system messages
- `registry.get_all_tools()` 全部工具的完整 schema 每轮发给 LLM

问题：上下文膨胀、无关工具稀释注意力、工具选择准确率下降。

**目标**：渐进式披露（progressive disclosure）——按需暴露工具/技能，同时**不降低 LLM 输入缓存命中率**。

## 2. 调研结论（官方文档依据）

### 各家缓存机制

| Provider | 官方定义 | tools 参与缓存？ |
|---|---|---|
| Anthropic | 缓存完整前缀，层级 `tools → system → messages`，自动找最长已缓存前缀；5 分钟 TTL，命中免费刷新 | ✅ 参与，且在最前 |
| OpenAI | ≥1024 tokens 自动启用；「exact prefix matches」；**tools 必须 identical** | ✅ 参与 |
| DeepSeek | 磁盘缓存默认启用；重叠前缀命中 | ✅ |

关键结论：**OpenAI 兼容格式下 tools 动态变化也影响缓存**（此前假设 tools 在顶层不参与缓存是错的）。

### Anthropic 官方渐进披露方案（Tool use with prompt caching）

> Deferred tools are not included in the system-prompt prefix. When the model discovers a deferred tool through tool search, the definition is appended inline as a `tool_reference` block in the conversation history. **The prefix is untouched, so prompt caching is preserved.**

- always-loaded 小工具集（带 `cache_control`）
- 大量 `defer_loading: true` 工具（不在前缀）
- tool search tool（regex / BM25 变体）发现工具
- 发现的工具定义以 `tool_reference` 块追加到**对话历史末尾**（后缀）→ 前缀不动 → 缓存保留
- 另有 `mid-conversation-tool-changes-2026-07-01` beta：中途增删工具不失效缓存

### OpenAI 兼容格式的关键约束

模型**只能调用 `tools` 参数里声明的工具**——Anthropic 的 `tool_reference` 是服务端机制，OpenAI 系没有。因此渐进披露需要应用层配合：**消息历史展示定义 + 后端把激活工具的 schema 追加到下一轮 `tools` 参数**。

## 3. 核心设计（已确认）

### 3.1 请求结构（每轮固定）

```
请求 =
  system: [基础提示] [固定工具目录] [已激活 skill 完整 prompt①]    ← 前缀，稳定
  messages: [历史…(append-only)] [最近: tool_reference 展示块②]
  tools:   [核心工具完整 schema: bash/file/memory + web_search③]   ← 前缀，固定
           [已激活 MCP 工具完整 schema（单调追加）]                  ← 前缀，只增
```

- ① skill 完整 prompt：**单调追加到 system 末尾**（激活后不撤销不重排）
- ② 渐进披露的工具定义：**作为 tool 消息追加到历史末尾**
- ③ 常用工具永远完整传入；其余工具只出现在目录

### 3.2 工具目录（system 内，固定顺序固定文案）

**每个工具一行摘要**（MCP 按**单个工具**粒度，不是整个 server）：

```
可用工具索引（调用 tool_search 获取完整定义）：
- bash_execute: 执行 shell 命令（完整定义已加载）
- github/list_repos: 列出仓库（延迟加载）
- slack/send_message: 发送 Slack 消息（延迟加载）
```

MCP 的 `tools/list` 返回单个工具的 name + description，截断成一行摘要即可。工具名用命名空间前缀（`server-name/tool-name`，Anthropic 官方推荐）。

### 3.3 skill 摘要

system 中一行摘要；激活后完整 prompt 单调追加到 system 末尾。

### 3.4 `tool_search` 工具（固定内置，模仿 Anthropic 自实现）

```json
{
  "name": "tool_search",
  "description": "按功能描述搜索可用工具，返回匹配工具的完整定义。当用户需求涉及当前未加载的工具时使用。",
  "parameters": { "query": "自然语言描述所需功能" }
}
```

执行流程：
1. LLM 需要延迟工具 → 调 `tool_search(query)`
2. 后端在本地工具索引（全部 MCP 工具 + 延迟 skill）检索：BM25 关键词匹配（后续可加 embedding），返回 top 3-5
3. 结果作为 tool 消息返回：每个匹配工具的完整 schema
4. 后端同时把匹配工具 schema **追加到下一轮 `tools` 参数**（单调，本会话保持）
5. 模型下一轮即可原生调用

缓存影响：`tool_search` 是固定工具（稳定）；激活工具追加到 tools 末尾（前缀稳定）。

### 3.5 设计规则

| 机制 | 做法 |
|---|---|
| 核心工具固定 | 内置工具（bash/file/memory）+ 高频工具（web_search）永远在 tools 最前，不重排 |
| 单调激活 | MCP/延迟工具激活后追加到 tools 末尾，会话内不撤销、不重排 |
| 目录固定 | system 目录排序和文案永不变化，新工具追加末尾 |
| tool_reference 等价 | 激活工具完整 schema 放消息历史末尾 + 下一轮 tools 追加 |
| skill 激活 | 完整 prompt 单调追加到 system 末尾 |

### 3.6 官方提醒

缓存前缀**仍占上下文窗口**（Anthropic 官方：caching 改变付费方式，不改变占用）。渐进披露核心收益是减少总上下文占用，缓存是叠加收益。

## 4. 影响模块（实施时参考）

- `backend/app/api/chat.py`：system 组装改为 基础 + 目录 + 激活集；tools 选择改为 核心 + 激活集
- `backend/app/skill/service.py`：`get_system_prompts` → 摘要目录 + 激活集；`get_skill_summaries`
- `backend/app/tool/registry.py`：工具索引（摘要/完整 schema/延迟标记）；`tool_search` 执行器
- `backend/app/runtime/`：Agent Loop 支持会话级激活集（单调）、tool_reference 展示块
- `backend/app/plugin/`：插件 skill 摘要生成
- `backend/app/mcp/`（迭代 B）：MCP 工具注册 + 摘要生成 + 生命周期
- 前端：Skills 页显示「延迟加载」状态（可选）

## 5. 决策记录

| # | 决策 | 依据 |
|---|---|---|
| 1 | skill 完整 prompt 放 system 末尾单调追加 | 前缀缓存稳定 |
| 2 | MCP 目录粒度 = 每工具一行摘要 | MCP tools/list 天然按工具 |
| 3 | tool_search 先 BM25，后续可加 embedding | Anthropic regex/BM25 变体 |
| 4 | 激活工具本会话保持（单调） | Anthropic 官方推荐 |
| 5 | 目录排序固定，新工具追加末尾 | 前缀稳定 |
| 6 | web_search 等高频工具直接完整传入 | 用户确认 |
| 7 | OpenAI 兼容格式需「消息展示 + tools 追加」双机制 | OpenAI 仅认 tools 参数声明 |
| 8 | 实施前不验证 mimo 缓存行为，按 Anthropic/OpenAI 规范保守设计 | 用户确认 |

## 6. 下一步

- 迭代 B：MCP 接入（stdio/streamable-http，注册进 ToolRegistry + 审批）
- 渐进式披露实施（本设计落地）：目录、激活集、tool_search
- 两者可合并为一个迭代（MCP 接入时天然需要渐进披露约束）
