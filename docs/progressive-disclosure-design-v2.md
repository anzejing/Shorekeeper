# 渐进式披露设计 v2 — 代理执行器方案

> 状态：**设计待确认**
> 日期：2026-08-07
> 关联：MCP 接入（迭代 B）、Skill/Tool 上下文管理
> 前置文档：`progressive-disclosure-design.md`（v1 方案）

---

## 1. 背景与动机

### 1.1 v1 方案的问题

v1 方案将新发现的工具 schema 追加到 `tools` 参数末尾、将 skill prompt 追加到 `system` 末尾。虽然追加不破坏**已有前缀**的缓存，但会破坏**前缀之后所有 messages 的缓存**：

```
tools:   [A,B,C] + 新工具 D        ← 前 3 个命中，D 不命中
system:  [基础] + [新 skill prompt]  ← 前缀命中，新内容不命中
messages: [m1...m10]                 ← 全部缓存失效 ❌（前缀变了）
```

10 轮对话的 messages 全部需要重新计算，即使一个字都没变。

### 1.2 核心诉求

**tools 参数和 system 消息永远不变**，只有 messages 在增长。这样已有 messages 的缓存完全不受影响。

### 1.3 OpenAI 调研结论

| 机制 | 说明 |
|---|---|
| `allowed_tools` | tools 数组全量放进去不变，per-request 控制可见范围（不影响缓存） |
| `tool_search`（GPT-5.4+）| 原生支持，工具注入末尾，缓存保留 |
| `prompt_cache_breakpoint`（GPT-5.6+）| 显式标记缓存边界 |

但 `allowed_tools` 和原生 `tool_search` 是 OpenAI 官方特性，第三方兼容 API（DeepSeek、vLLM 等）不一定支持。本方案采用**应用层代理执行器**，对所有 provider 通用。

---

## 2. 设计目标

| # | 目标 | 验收标准 |
|---|---|---|
| G1 | tools 参数永远不变 | 会话生命周期内 tools 数组内容和顺序完全一致 |
| G2 | system 消息永远不变 | 会话生命周期内 system 内容完全一致 |
| G3 | messages append-only | 历史消息不修改、不重排 |
| G4 | 动态工具可被发现和使用 | LLM 能通过 tool_search 发现工具、通过 tool_executor 调用 |
| G5 | 动态工具参数准确 | 参数校验 + 详细错误提示，引导 LLM 自行修正 |
| G6 | 安全审批不绕过 | 动态工具走完整权限审批流程 |
| G7 | 缓存零破坏 | 任何动态变化都不破坏已有前缀和 messages 的缓存 |

---

## 3. 核心设计

### 3.1 请求结构（每轮完全一致）

```
请求 =
  system:  [基础提示 + 工具目录 + skill 目录]     ← 永远不变
  tools:   [bash, file, memory, read_memory,
            write_memory, search_memory,
            tool_search, tool_executor]             ← 永远不变，8 个工具
  messages: [历史...(append-only)]                  ← 只追加
```

**缓存效果**：tools 和 system 完全静态，messages 中已有部分 100% 命中缓存。只有当前轮新增的 user 消息和 tool 结果不命中。

### 3.2 工具分类

#### 固定工具（核心，直接可用）

| 工具名 | 来源 | 说明 |
|---|---|---|
| `bash_execute` | tools/bash.py | 执行 shell 命令 |
| `read_file` | tools/file.py | 读文件 |
| `write_file` | tools/file.py | 写文件 |
| `read_memory` | memory/tools.py | 读长期记忆 |
| `write_memory` | memory/tools.py | 写长期记忆 |
| `search_memory` | memory/tools.py | 搜索记忆 |

#### 代理工具（固定注册，代理动态能力）

| 工具名 | 说明 |
|---|---|
| `tool_search` | 搜索可用工具，返回匹配工具的完整定义 |
| `tool_executor` | 通用执行器，路由到任意已注册工具 |

### 3.3 `tool_search` 设计

```json
{
  "name": "tool_search",
  "description": "搜索可用工具。当你需要执行某个操作但不确定是否有对应工具时调用。返回匹配工具的名称、描述和完整参数定义。使用 tool_executor 调用搜索到的工具。",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "自然语言描述你需要的功能，例如 '发送 Slack 消息'、'读取 GitHub PR'、'查询数据库'"
      },
      "category": {
        "type": "string",
        "description": "可选，按分类筛选：mcp（MCP 服务器工具）、skill（技能工具）、plugin（插件工具）",
        "enum": ["mcp", "skill", "plugin"]
      }
    },
    "required": ["query"]
  }
}
```

**返回格式**（tool 消息内容）：

```
找到 3 个匹配工具：

## 1. github/list_repos
描述：列出指定用户的 GitHub 仓库
参数：
  - owner (string, 必填): 仓库所有者用户名
  - per_page (integer, 可选, 默认 30): 每页数量，最大 100
  - sort (string, 可选): 排序方式，可选 updated/created/pushed

## 2. github/create_issue
描述：在指定仓库创建 Issue
参数：
  - owner (string, 必填): 仓库所有者
  - repo (string, 必填): 仓库名
  - title (string, 必填): Issue 标题
  - body (string, 可选): Issue 内容
  - labels (array of string, 可选): 标签列表

## 3. github/search_code
描述：搜索 GitHub 代码
参数：
  - query (string, 必填): 搜索查询
  - per_page (integer, 可选, 默认 30): 每页数量

---
使用方法：调用 tool_executor，tool_name 填工具名（如 github/list_repos），arguments 填参数对象。
```

**搜索算法**：
- 第一阶段：BM25 关键词匹配（基于工具名 + description）
- 第二阶段（可选）：embedding 语义搜索
- 返回 top 5 结果

### 3.4 `tool_executor` 设计

```json
{
  "name": "tool_executor",
  "description": "执行任意已注册工具。先用 tool_search 获取工具定义和参数格式，再调用本工具执行。tool_name 必须填完整工具名（如 bash_execute、github/list_repos）。",
  "parameters": {
    "type": "object",
    "properties": {
      "tool_name": {
        "type": "string",
        "description": "要执行的工具名称，必须是 tool_search 返回的完整名称"
      },
      "arguments": {
        "type": "object",
        "description": "工具参数，必须严格匹配该工具的参数定义（参见 tool_search 返回的参数说明）"
      }
    },
    "required": ["tool_name", "arguments"]
  }
}
```

### 3.5 参数校验与错误反馈（关键）

tool_executor 的核心难点是 LLM 不一定传对参数。设计**三层校验 + 详细反馈**：

#### 第一层：工具存在性校验

```python
# 工具不存在 → 返回详细错误 + 搜索建议
if tool_name not in registry:
    return ToolResult(
        is_error=True,
        content=f"工具 '{tool_name}' 不存在。\n"
                f"请先调用 tool_search(query='...') 查找正确的工具名。\n"
                f"可用的固定工具: bash_execute, read_file, write_file, "
                f"read_memory, write_memory, search_memory"
    )
```

#### 第二层：必填参数校验

```python
# 根据 tool_def.parameters（JSON Schema）校验 required 字段
schema = tool_def.parameters
required = schema.get("required", [])
missing = [p for p in required if p not in tool_call.arguments]
if missing:
    return ToolResult(
        is_error=True,
        content=f"工具 '{tool_name}' 缺少必填参数: {missing}\n"
                f"参数定义:\n{format_schema(schema)}\n"
                f"你提供的参数: {json.dumps(arguments)}\n"
                f"请补充缺失的参数后重新调用 tool_executor。"
    )
```

#### 第三层：参数类型校验

```python
# 校验每个参数的类型（string/integer/boolean/array/object）
for param_name, param_value in arguments.items():
    param_def = properties.get(param_name)
    if param_def is None:
        # 未知参数 → 警告但不阻止（容错）
        warnings.append(f"参数 '{param_name}' 不在定义中，将被忽略")
        continue
    if not check_type(param_value, param_def):
        return ToolResult(
            is_error=True,
            content=f"参数 '{param_name}' 类型错误: "
                    f"期望 {param_def['type']}，实际 {type(param_value).__name__}\n"
                    f"参数定义: {json.dumps(param_def, ensure_ascii=False)}"
        )
```

#### 错误消息模板

所有错误消息遵循统一格式，引导 LLM 自行修正：

```
❌ 工具执行失败: {tool_name}

错误原因: {具体原因}

参数定义:
{从 tool_def 格式化的人类可读参数表}

你提供的参数:
{LLM 传入的参数}

修正建议:
{针对该错误的具体修正建议}

提示: 如果不确定工具的参数格式，请先调用 tool_search 查询。
```

### 3.6 Skill 处理

#### System 中只放摘要目录（固定不变）

```
可用技能索引（调用 tool_search 搜索技能，或直接使用已加载的技能）：
- code_review: 代码审查，检查代码质量和规范
- deploy: 部署应用到生产环境
- test_generator: 自动生成单元测试
- git_workflow: Git 工作流管理（分支、PR、合并）
```

#### Skill 激活方式

1. LLM 调用 `tool_search(query="代码审查")` → 返回 skill 的完整 prompt
2. 或者：system 检测到用户消息中的关键词 → 在 tool_search 结果中标记相关 skill

#### Skill Prompt 注入策略

**不注入 system，作为 tool 消息返回**：

```
# code_review Skill

## 使用方法
这是一个代码审查技能。请按照以下步骤执行：
1. 读取目标文件
2. 检查代码规范...
3. 输出审查报告...

## 审查规则
- ...
```

LLM 读到后，按 skill prompt 中的指示行动。skill prompt 作为消息历史的一部分，不会破坏 system 缓存。

---

## 4. 审批与安全

### 4.1 动态工具的审批流程

tool_executor 执行动态工具时，**必须经过完整的权限审批流程**：

```
LLM 调用 tool_executor(tool_name="github/create_issue", arguments={...})
  ↓
ToolExecutor 拦截 → 参数校验
  ↓
PermissionInterceptor → PermissionEngine.evaluate()
  ↓
  ├── ALLOW → 直接执行
  ├── DENY → 拒绝，返回原因给 LLM
  └── REQUIRE_APPROVAL → 创建审批 → Run 暂停 → 等待用户审批
       ↓
       用户审批通过 → 恢复执行 → 实际调用 github/create_issue
```

### 4.2 权限规则配置

动态工具默认走 `system.execute_dynamic` 规则：

```python
# 系统规则示例
PermissionRule(
    rule_id="system.execute_dynamic",
    capability="system.execute_dynamic",
    layer=PermissionRuleLayer.SYSTEM_GUARDRAIL,
    policy=PermissionResult.REQUIRE_APPROVAL,  # 默认需要审批
    description="所有通过 tool_executor 执行的动态工具默认需要审批",
)
```

管理员可为特定工具配置更宽松的规则：

```python
# 允许特定 MCP 工具直接执行
PermissionRule(
    rule_id="allow.github.read",
    tool_name="github/list_repos",
    capability="mcp.github.read",
    layer=PermissionRuleLayer.TEAM,
    policy=PermissionResult.ALLOW,
    description="GitHub 只读操作允许直接执行",
)
```

### 4.3 tool_search 的安全性

tool_search 本身是只读操作（READ_ONLY），不触发审批。但它返回的工具定义可能包含敏感信息（如 API 端点、参数格式），这在当前设计下可接受——LLM 本身就需要这些信息才能正确调用。

---

## 5. 数据流

### 5.1 标准对话流程

```
用户消息
  ↓
Assistant Service 组装请求:
  system: [基础提示 + 工具目录 + skill 目录]（固定）
  tools:  [8 个固定工具 schema]（固定）
  messages: [历史 + 用户消息]
  ↓
LiteLLM → LLM
  ↓
LLM 返回:
  ├── 文本回复 → 直接返回
  ├── 调用固定工具（bash/file/memory）→ 直接执行
  ├── 调用 tool_search → 搜索工具 → 返回工具定义
  └── 调用 tool_executor → 参数校验 → 权限审批 → 执行
  ↓
结果回填 messages → 下一轮
```

### 5.2 动态工具发现流程

```
LLM 判断需要发送 Slack 消息
  ↓
调用 tool_search(query="发送 Slack 消息")
  ↓
BM25 搜索 → 返回 slack/send_message 的完整定义
  ↓
LLM 阅读参数定义，构造参数
  ↓
调用 tool_executor(tool_name="slack/send_message", arguments={channel: "#general", text: "hello"})
  ↓
tool_executor:
  1. 参数校验（必填/类型）
  2. 权限检查（PermissionInterceptor）
  3. 审批（如需要）→ Run 暂停 → 用户审批 → 恢复
  4. 路由到 slack 执行器
  ↓
返回执行结果
```

### 5.3 Skill 激活流程

```
用户: "帮我审查这段代码"
  ↓
LLM 调用 tool_search(query="代码审查")
  ↓
返回 code_review skill 的完整 prompt
  ↓
LLM 阅读 skill prompt，按指示执行:
  1. 调用 read_file 读取目标文件
  2. 按 skill prompt 中的审查规则检查
  3. 输出审查报告
```

---

## 6. 实施方案

### 6.1 模块变更清单

| 模块 | 变更 | 说明 |
|---|---|---|
| `tool/registry.py` | **新增** ToolIndex | 工具索引，支持 BM25 搜索 |
| `tool/search.py` | **新增** | tool_search 执行器 |
| `tool/proxy_executor.py` | **新增** | tool_executor 代理执行器 |
| `tool/schema_validator.py` | **新增** | 参数校验 + 错误消息生成 |
| `skill/service.py` | **修改** | get_system_prompts → 返回摘要目录 |
| `skill/service.py` | **新增** | get_skill_summaries() |
| `api/chat.py` | **修改** | system 组装改为固定结构 |
| `runtime/loop.py` | **不变** | Agent Loop 无需修改 |
| `runtime/runtime.py` | **不变** | 无需修改 |
| `permission/engine.py` | **新增** system.execute_dynamic 规则 | 动态工具默认规则 |
| `main.py` | **修改** | 初始化新模块、注册新工具 |

### 6.2 实施步骤（按依赖顺序）

#### Phase 1: 基础设施（无外部依赖）

**Step 1.1: ToolIndex — 工具索引**

```python
# tool/index.py
class ToolIndex:
    """工具索引——支持搜索的工具元数据存储。

    不存储执行器，只存储 ToolDef + 分类标签。
    供 tool_search 使用。
    """

    def __init__(self) -> None:
        self._entries: dict[str, ToolIndexEntry] = []

    def add(self, entry: ToolIndexEntry) -> None:
        """添加工具到索引。"""

    def remove(self, tool_name: str) -> None:
        """从索引移除工具。"""

    def search(self, query: str, category: str | None = None, limit: int = 5) -> list[ToolIndexEntry]:
        """BM25 搜索工具。"""

    def get(self, tool_name: str) -> ToolIndexEntry | None:
        """按名称获取工具索引条目。"""

    def list_all(self) -> list[ToolIndexEntry]:
        """列出所有索引条目。"""

@dataclass
class ToolIndexEntry:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    category: str               # core / mcp / skill / plugin
    source: str                 # 来源标识
    tags: list[str]             # 搜索标签
```

**Step 1.2: SchemaValidator — 参数校验**

```python
# tool/schema_validator.py
class SchemaValidator:
    """JSON Schema 参数校验器。

    校验 LLM 传入的参数是否符合工具定义。
    返回详细的错误信息，引导 LLM 自行修正。
    """

    def validate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        schema: dict[str, Any],
    ) -> ValidationResult:
        """校验参数。

        Returns:
            ValidationResult:
            - valid: bool
            - errors: list[str] — 每个错误的详细描述
            - warnings: list[str] — 非阻塞警告
            - suggestion: str — 修正建议
        """

@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[str]
    suggestion: str
```

**Step 1.3: ToolSearchExecutor — tool_search 执行器**

```python
# tool/search.py
class ToolSearchExecutor:
    """tool_search 工具执行器。

    接收自然语言查询，返回匹配工具的完整定义。
    """

    def __init__(self, index: ToolIndex) -> None:
        self._index = index

    async def execute(
        self,
        tool_call: ToolCall,
        **kwargs,
    ) -> ToolResult:
        query = tool_call.arguments.get("query", "")
        category = tool_call.arguments.get("category")
        results = self._index.search(query, category=category, limit=5)
        # 格式化返回
        ...
```

**Step 1.4: ProxyToolExecutor — tool_executor 代理执行器**

```python
# tool/proxy_executor.py
class ProxyToolExecutor:
    """代理执行器——路由到任意已注册工具。

    流程：
    1. 参数校验（SchemaValidator）
    2. 权限检查（PermissionInterceptor）
    3. 路由到实际工具执行器
    """

    def __init__(
        self,
        registry: ToolRegistry,
        validator: SchemaValidator,
    ) -> None:
        self._registry = registry
        self._validator = validator

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        tool_name = tool_call.arguments.get("tool_name", "")
        arguments = tool_call.arguments.get("arguments", {})

        # 1. 工具存在性校验
        tool_def = self._registry.get_tool(tool_name)
        if tool_def is None:
            return self._format_not_found(tool_name)

        # 2. 参数校验
        validation = self._validator.validate(tool_name, arguments, tool_def.parameters)
        if not validation.valid:
            return self._format_validation_error(tool_name, arguments, tool_def, validation)

        # 3. 警告（不阻止执行）
        warning_text = ""
        if validation.warnings:
            warning_text = "⚠️ 警告:\n" + "\n".join(validation.warnings) + "\n\n"

        # 4. 构造实际 ToolCall 并执行
        actual_call = ToolCall(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
        )
        result = await self._registry.execute(actual_call, cancellation=cancellation, context=context)

        # 5. 附加警告到结果
        if warning_text and not result.is_error:
            result.content.insert(0, TextPart(text=warning_text))

        return result
```

#### Phase 2: 集成到现有系统

**Step 2.1: 修改 SkillService — 摘要目录**

```python
# skill/service.py 新增方法
async def get_skill_summaries(self) -> str:
    """生成 skill 摘要目录（固定文本，注入 system）。

    格式：
    可用技能索引（调用 tool_search 搜索技能，或直接使用已加载的技能）：
    - code_review: 代码审查，检查代码质量和规范
    - deploy: 部署应用到生产环境
    """
    states = await self._store.list(enabled=True)
    lines = ["可用技能索引（调用 tool_search 搜索技能获取详细使用方法）："]
    for state in states:
        info = self._info_cache.get(state.name)
        if info:
            lines.append(f"- {info.name}: {info.description}")
    return "\n".join(lines)
```

**Step 2.2: 修改 Chat API — 固定 system 组装**

```python
# api/chat.py 修改 _prepare_session_and_run

async def _prepare_session_and_run(request):
    # ...
    # 4. 组装固定 system prompt
    system_parts = [
        BASE_SYSTEM_PROMPT,                    # 基础提示（固定）
        _build_tool_directory(registry),       # 工具目录（固定）
        await skill.get_skill_summaries(),     # Skill 摘要（固定）
    ]
    system_message = Message(
        role=Role.SYSTEM,
        content="\n\n".join(system_parts),
    )

    # 5. 组装 messages
    messages = [system_message]
    for msg in context:
        messages.append(Message(role=Role(msg.role), content=msg.content))

    # 6. 固定 tools 列表
    tools = _get_fixed_tools()

    # ...
```

**Step 2.3: 注册新工具到 ToolRegistry**

```python
# main.py 初始化时

# 1. 创建 ToolIndex
tool_index = ToolIndex()

# 2. 注册核心工具到 registry 和 index
for tool_def in CORE_TOOLS:
    registry.register(tool_def, executor)
    tool_index.add(ToolIndexEntry.from_tool_def(tool_def, category="core"))

# 3. 创建代理工具
search_executor = ToolSearchExecutor(tool_index)
proxy_executor = ProxyToolExecutor(registry, SchemaValidator())

# 4. 注册 tool_search 和 tool_executor
registry.register(TOOL_SEARCH_DEF, search_executor)
registry.register(TOOL_EXECUTOR_DEF, proxy_executor)
```

**Step 2.4: MCP 工具注册到 ToolIndex（迭代 B）**

```python
# MCP 工具发现后
for mcp_tool in mcp_tools:
    # 只注册到 index（不注册到 registry 的固定 tools）
    tool_index.add(ToolIndexEntry(
        name=f"{server_name}/{mcp_tool.name}",
        description=mcp_tool.description,
        parameters=mcp_tool.input_schema,
        category="mcp",
        source=server_name,
        tags=mcp_tool.tags,
    ))
    # 注册到 registry（供 proxy_executor 路由执行）
    registry.register(tool_def, mcp_executor)
```

#### Phase 3: 测试与验证

**Step 3.1: 单元测试**

| 测试文件 | 测试内容 |
|---|---|
| `test_tool_index.py` | BM25 搜索准确性、边界情况 |
| `test_schema_validator.py` | 参数校验（必填/类型/enum/嵌套）|
| `test_proxy_executor.py` | 路由、校验、错误消息 |
| `test_tool_search.py` | 搜索 + 格式化输出 |

**Step 3.2: 集成测试 — LLM 执行度验证**

核心测试：**验证 LLM 能否正确使用 tool_search + tool_executor 两步调用模式**。

```python
# test_llm_tool_usage.py

async def test_llm_discovers_and_uses_dynamic_tool():
    """LLM 应该能：1. 搜索工具 2. 阅读定义 3. 正确调用"""

    # 1. 注册一个模拟的 MCP 工具到 index
    index.add(ToolIndexEntry(
        name="slack/send_message",
        description="发送 Slack 消息",
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "频道名"},
                "text": {"type": "string", "description": "消息内容"},
            },
            "required": ["channel", "text"],
        },
        category="mcp",
        source="slack",
        tags=["slack", "消息", "发送"],
    ))

    # 2. 发送用户消息
    response = await chat("帮我发一条 Slack 消息到 #general 频道，内容是 hello")

    # 3. 验证 LLM 的行为
    #    预期：先调用 tool_search → 再调用 tool_executor
    assert "slack/send_message" in response.tool_calls
    assert response.status == "completed"

async def test_llm_handles_missing_params():
    """LLM 缺少必填参数时，应能从错误消息中学习并修正"""

    # 1. LLM 第一次调用缺少 channel
    # 2. tool_executor 返回详细错误
    # 3. LLM 第二次调用补充 channel
    # 4. 验证最终成功
    ...

async def test_llm_handles_type_error():
    """LLM 传错类型时，应能从错误消息中修正"""

    # 1. LLM 传 per_page="abc"（应为 integer）
    # 2. tool_executor 返回类型错误
    # 3. LLM 修正为 per_page=30
    ...
```

---

## 7. 工具目录格式（System 内，固定）

```
## 可用工具

你可以直接使用以下工具（直接调用，无需搜索）：

| 工具 | 说明 |
|---|---|
| bash_execute | 执行 shell 命令 |
| read_file | 读取文件内容 |
| write_file | 写入文件 |
| read_memory | 读取长期记忆 |
| write_memory | 写入长期记忆 |
| search_memory | 搜索记忆和历史对话 |
| tool_search | 搜索更多工具（MCP、插件等） |
| tool_executor | 执行搜索到的工具 |

当你需要执行上述 6 个核心工具之外的操作时：
1. 先调用 tool_search(query="你需要的功能") 搜索工具
2. 阅读返回的工具定义和参数格式
3. 调用 tool_executor(tool_name="工具名", arguments={...}) 执行
```

---

## 8. 缓存效果分析

### 静态场景（无动态工具）

```
tools:   [8 个工具 schema]        ← 完全不变，100% 缓存
system:  [基础 + 目录 + skill]    ← 完全不变，100% 缓存
messages: [m1...m10]              ← 历史不动，100% 缓存
新消息:  [user msg + tool result] ← 唯一不命中的部分
```

### 动态场景（使用 MCP 工具）

```
tools:   [8 个工具 schema]        ← 不变，100% 缓存
system:  [基础 + 目录 + skill]    ← 不变，100% 缓存
messages: [m1...m10]              ← 不变，100% 缓存
新消息:  [tool_search 结果]       ← 不命中（几百 tokens）
新消息:  [tool_executor 结果]     ← 不命中
```

**对比 v1 方案**：v1 追加 tools/system 会导致 m1...m10 全部失效（几万 tokens）。v2 方案只有新增的消息不命中。

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解策略 |
|---|---|---|
| LLM 不会用两步调用 | 工具调用失败率高 | system prompt 明确说明流程；tool_executor 错误消息引导 |
| tool_executor 是黑盒 | 难以区分路由问题还是工具本身问题 | 错误消息包含完整调用链信息 |
| 复杂参数 LLM 填错 | 执行失败 | 三层校验 + 详细错误反馈 + 类型修正建议 |
| tool_search 搜索不准 | LLM 找不到需要的工具 | BM25 + 标签系统 + 可扩展 embedding |
| 安全：tool_executor 绕过审批 | 安全风险 | proxy_executor 内部走完整权限流程 |
| 大量 MCP 工具的 index 内存占用 | 内存 | index 只存元数据，不含执行器 |

---

## 10. 后续演进

| 阶段 | 内容 |
|---|---|
| Phase 1（当前） | 核心框架：ToolIndex + SchemaValidator + tool_search + tool_executor |
| Phase 2 | MCP 接入：MCP 工具注册到 ToolIndex |
| Phase 3 | Skill 搜索：skill 也通过 tool_search 搜索 |
| Phase 4 | 优化：embedding 语义搜索、工具使用统计、自动推荐 |

---

## 11. 决策记录

| # | 决策 | 依据 |
|---|---|---|
| 1 | tools/system 完全固定 | 零缓存破坏 |
| 2 | 代理执行器而非追加 schema | 兼容所有 provider，缓存最稳定 |
| 3 | tool_search 返回完整参数定义 | LLM 需要精确信息才能正确构造参数 |
| 4 | 三层参数校验 + 详细错误 | 提升 LLM 自修正能力 |
| 5 | 动态工具走完整审批流程 | 安全不妥协 |
| 6 | Skill prompt 作为 tool 消息返回而非 system | 不破坏 system 缓存 |
| 7 | BM25 优先，embedding 可选 | 简单可靠，渐进优化 |
