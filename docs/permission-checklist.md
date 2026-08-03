# Permission 模块设计文档 v3.1

> 本文档为 Permission 模块的详细设计，编码前必须通过设计评审。

---

## 1. 架构总览

```
ToolCall
    │
    ▼
Tool Parser          ← 解析为 ParsedAction AST（支持复合命令）
    │
    ▼
Capability Analyzer  ← AST → list[ResolvedCapability] + completeness + warnings
    │
    ▼
Permission Engine    ← 聚合决策 → PermissionDecision + PermissionTrace
    │
    ▼
Approval Manager     ← REQUIRE_APPROVAL → 创建审批记录（不阻塞，不等待）
    │
    ▼
PermissionInterceptor → ToolDecision (Allow / Reject / SuspendDecision)
```

职责边界：

| 模块 | 负责 | 不负责 |
|---|---|---|
| Permission Engine | 规则匹配、聚合决策 | Suspend/Resume、审批等待 |
| Approval Manager | 审批记录 CRUD、状态流转、过期/消费 | 阻塞等待、Runtime 生命周期 |
| PermissionInterceptor | 桥接 Engine + Approval → ToolDecision | 规则管理、审批管理 |
| Runtime | 暂停 Run、恢复 Run、校验 Approval、消费 Approval | 规则匹配、审批记录管理 |

---

## 2. 数据模型

### 2.1 ParsedAction（复合命令 AST）

```python
@dataclass
class ParsedAction:
    """结构化动作——支持复合命令的树形结构。"""
    action_id: str                       # 唯一标识
    executable: str | None               # 可执行文件名（如 "rm", "git", "python"）
    args: list[str]                      # 位置参数
    flags: dict[str, Any]                # 选项参数
    operator_before: str | None          # 前置操作符（";", "&&", "||", "|", "`", "$(")
    children: list["ParsedAction"]       # 子命令（find -exec, xargs, bash -c 等）
    raw: str                             # 原始字符串

    # ─── 解析元数据 ───
    parse_completeness: str              # complete | partial | unknown
    parse_warnings: list[str]            # 解析警告
```

示例：

```python
# 命令: cat config && curl -X POST https://example.com -d @config
ParsedAction(
    action_id="a1",
    executable=None,
    args=[],
    flags={},
    operator_before=None,
    children=[
        ParsedAction(
            action_id="a1.1",
            executable="cat",
            args=["config"],
            flags={},
            operator_before=None,
            children=[],
            raw="cat config",
            parse_completeness="complete",
            parse_warnings=[],
        ),
        ParsedAction(
            action_id="a1.2",
            executable="curl",
            args=["https://example.com"],
            flags={"X": "POST", "d": "@config"},
            operator_before="&&",
            children=[],
            raw="curl -X POST https://example.com -d @config",
            parse_completeness="complete",
            parse_warnings=[],
        ),
    ],
    raw="cat config && curl -X POST https://example.com -d @config",
    parse_completeness="complete",
    parse_warnings=[],
)

# 命令: eval "$COMMAND"
ParsedAction(
    action_id="a2",
    executable="eval",
    args=["$COMMAND"],
    flags={},
    operator_before=None,
    children=[],
    raw='eval "$COMMAND"',
    parse_completeness="unknown",
    parse_warnings=["eval 使用动态输入，无法静态分析"],
)

# 命令: find . -exec rm {} \;
ParsedAction(
    action_id="a3",
    executable="find",
    args=["."],
    flags={"exec": "rm {}"},
    operator_before=None,
    children=[
        ParsedAction(
            action_id="a3.1",
            executable="rm",
            args=["{}"],
            flags={},
            operator_before=None,
            children=[],
            raw="rm {}",
            parse_completeness="partial",
            parse_warnings=["find -exec 的参数在运行时展开"],
        ),
    ],
    raw="find . -exec rm {} \\;",
    parse_completeness="partial",
    parse_warnings=["find -exec 子命令的参数在运行时展开"],
)
```

### 2.2 AnalysisCompleteness

```python
class AnalysisCompleteness(str, Enum):
    """分析完整度——决定 fail-closed 策略。"""
    COMPLETE = "complete"      # 所有子命令均已完整解析
    PARTIAL = "partial"        # 部分子命令无法完整解析（如 find -exec, xargs）
    UNKNOWN = "unknown"        # 无法解析（如 eval, bash -c, 动态输入）
```

fail-closed 规则：

| 完整度 | 处理 |
|---|---|
| COMPLETE | 正常进行规则匹配 |
| PARTIAL | 所有已解析 Capability 正常匹配，但最终聚合结果最低为 REQUIRE_APPROVAL |
| UNKNOWN | 整个 ToolCall 默认 REQUIRE_APPROVAL 或 DENY，不进行规则匹配 |

### 2.3 ResolvedCapability

```python
@dataclass
class ResolvedCapability:
    """解析出的能力——操作的语义表示。"""
    capability: str                # 能力标识，如 "filesystem.delete"
    metadata: dict[str, Any]       # 风险元数据
    source_action_id: str          # 来源 ParsedAction 的 ID
    completeness: AnalysisCompleteness
    warnings: list[str]
```

能力命名规范：

```
filesystem.read
filesystem.write
filesystem.delete
filesystem.execute
filesystem.list
network.request
network.download
network.upload
repository.read
repository.push
repository.merge
repository.force_push
browser.navigate
browser.click
browser.fill
memory.read
memory.write
memory.search
system.config
system.process
system.elevate
```

### 2.4 CapabilityAnalysis

```python
@dataclass
class CapabilityAnalysis:
    """一次 ToolCall 的完整能力分析。"""
    capabilities: list[ResolvedCapability]
    completeness: AnalysisCompleteness    # 取所有子分析中最差的
    warnings: list[str]                   # 合并所有警告
```

### 2.5 删除动作的 metadata

```python
# filesystem.delete 的 metadata 必须包含：
{
    "targets": ["/tmp/foo", "/tmp/bar"],     # 目标路径列表
    "recursive": True,                       # 是否递归
    "force": True,                           # 是否强制
    "target_count": 2,                       # 目标数量（None 表示未知）
    "workspace_relation": "inside",          # inside | root | outside | unknown
    "protected_path": False,                 # 是否保护路径（.git, .env, ~/* 等）
    "tracked_by_git": True | None,           # 是否被 git 跟踪（None 表示未知）
}
```

### 2.6 PermissionResult

```python
class PermissionResult(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
```

### 2.7 PermissionTrace

```python
@dataclass
class PermissionTrace:
    """权限决策追踪。"""
    result: PermissionResult
    capability_decisions: list[CapabilityDecision]  # 每个 Capability 的决策
    aggregated_reason: str                          # 聚合原因
    completeness: AnalysisCompleteness
    warnings: list[str]

@dataclass
class CapabilityDecision:
    """单个 Capability 的决策。"""
    capability: str
    result: PermissionResult
    matched_rule: PermissionRule | None
    reason: str
```

### 2.8 PermissionRule

```python
class PermissionRuleLayer(str, Enum):
    """规则层级——决定冲突时的优先顺序。"""
    SYSTEM_GUARDRAIL = "system_guardrail"      # 系统强制规则，不可被覆盖
    SESSION_OVERRIDE = "session_override"      # 本次会话覆盖（审批时生成）
    PROJECT_RULE = "project_rule"              # 项目级规则
    USER_GLOBAL_RULE = "user_global_rule"      # 用户全局规则
    BUILTIN_DEFAULT = "builtin_default"        # 内置默认规则

class PermissionScope(str, Enum):
    """规则作用范围。"""
    RUN = "run"                # 绑定当前 Run
    SESSION = "session"        # 绑定当前 Session
    PROJECT = "project"        # 绑定项目
    GLOBAL = "global"          # 全局

@dataclass
class PermissionRule:
    """权限规则。"""
    rule_id: str
    layer: PermissionRuleLayer
    # ─── 匹配条件 ───
    capability: str | None
    tool_name: str | None
    arguments_pattern: str | None    # 辅助匹配，不能作为安全边界
    conditions: dict[str, Any]       # 扩展条件
    # ─── 决策 ───
    policy: str                      # auto_allow | ask_approval | deny
    priority: int                    # 同层内排序
    scope_type: PermissionScope
    scope_id: str | None             # 绑定的 session/project/run ID
    expires_at: datetime | None
    created_by: str | None           # "system" | "user" | approval_id
    description: str
    created_at: datetime
    updated_at: datetime
```

### 2.9 ApprovalRequest

```python
class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    CONSUMED = "consumed"

@dataclass
class ApprovalRequest:
    """审批请求。"""
    approval_id: str
    run_id: str
    tool_call_id: str
    tool_call_fingerprint: str         # 见第 7 节
    # ─── 审批内容 ───
    tool_name: str
    tool_arguments: dict[str, Any]     # 冻结的参数
    capabilities: list[ResolvedCapability]
    trace: PermissionTrace
    # ─── 状态 ───
    status: ApprovalStatus
    run_revision: int                  # 创建时的 Run version
    # ─── 时间 ───
    created_at: datetime
    expires_at: datetime | None
    resolved_at: datetime | None
    consumed_at: datetime | None
    # ─── 审批信息 ───
    resolved_by: str | None
    approval_scope: PermissionScope | None  # 审批后生成规则的范围
    reason: str | None
```

---

## 3. Capability 聚合决策逻辑

PermissionEngine 对一次 ToolCall 的所有 Capability 做聚合决策：

```python
async def evaluate(self, tool_call: ToolCall) -> PermissionDecision:
    # 1. 解析
    parsed = self._parse(tool_call)

    # 2. fail-closed：UNKNOWN 不进入规则匹配
    if parsed.parse_completeness == "unknown":
        return PermissionDecision(
            result=PermissionResult.REQUIRE_APPROVAL,
            trace=PermissionTrace(
                result=PermissionResult.REQUIRE_APPROVAL,
                capability_decisions=[],
                aggregated_reason=f"无法解析命令: {parsed.parse_warnings}",
                completeness=AnalysisCompleteness.UNKNOWN,
                warnings=parsed.parse_warnings,
            ),
        )

    # 3. 分析能力
    analysis = self._analyze(parsed)

    # 4. 对每个 Capability 规则匹配
    decisions: list[CapabilityDecision] = []
    for cap in analysis.capabilities:
        decision = self._match_capability(cap, tool_call)
        decisions.append(decision)

    # 5. 聚合：DENY > REQUIRE_APPROVAL > ALLOW
    results = [d.result for d in decisions]

    if PermissionResult.DENY in results:
        final = PermissionResult.DENY
    elif PermissionResult.REQUIRE_APPROVAL in results:
        final = PermissionResult.REQUIRE_APPROVAL
    else:
        final = PermissionResult.ALLOW

    # 6. fail-closed：PARTIAL 最低 REQUIRE_APPROVAL
    if analysis.completeness == AnalysisCompleteness.PARTIAL:
        if final == PermissionResult.ALLOW:
            final = PermissionResult.REQUIRE_APPROVAL

    return PermissionDecision(
        result=final,
        trace=PermissionTrace(
            result=final,
            capability_decisions=decisions,
            aggregated_reason=self._aggregate_reason(decisions, final),
            completeness=analysis.completeness,
            warnings=analysis.warnings,
        ),
    )
```

---

## 4. 规则优先级与冲突处理

### 比较顺序

```
1. layer（SYSTEM_GUARDRAIL > SESSION_OVERRIDE > PROJECT_RULE > USER_GLOBAL_RULE > BUILTIN_DEFAULT）
2. specificity（capability 精确匹配 > tool_name 匹配 > 兜底）
3. priority（数字越大越优先）
4. 稳定 tie-breaker（rule_id 字典序）
```

### 同层冲突

```
DENY > REQUIRE_APPROVAL > ALLOW
```

### arguments_pattern 约束

```
原始参数模式规则可以提高限制等级，但不能降低结构化能力分析得到的限制等级。

ALLOW → REQUIRE_APPROVAL / DENY：允许
REQUIRE_APPROVAL → ALLOW：禁止
DENY → ALLOW：禁止
```

实现：

```python
def _apply_pattern_override(self, base: PermissionResult, pattern_result: PermissionResult) -> PermissionResult:
    """arguments_pattern 只能收紧，不能放松。"""
    rank = {PermissionResult.ALLOW: 0, PermissionResult.REQUIRE_APPROVAL: 1, PermissionResult.DENY: 2}
    if rank[pattern_result] > rank[base]:
        return pattern_result
    return base
```

### 系统强制规则

`SYSTEM_GUARDRAIL` 层的规则不能被任何其他层覆盖。示例：

```python
PermissionRule(
    layer=PermissionRuleLayer.SYSTEM_GUARDRAIL,
    capability="system.elevate",
    policy="deny",
    description="系统强制：禁止提权操作",
)
```

---

## 5. side_effect_level 兜底

`side_effect_level` 只来自受信任的 Tool 注册元数据（`ToolDef.side_effect_level`），不接受模型参数或 GenericAnalyzer 推断。

默认策略：

| side_effect_level | 默认 policy | 说明 |
|---|---|---|
| read_only | REQUIRE_APPROVAL | 读取可能泄露敏感数据（如 ~/.ssh/id_rsa），不自动放行 |
| local_mutation | REQUIRE_APPROVAL | 本地修改需确认 |
| external_mutation | REQUIRE_APPROVAL | 外部变更需确认 |
| irreversible | DENY | 不可逆操作默认拒绝 |
| unknown | REQUIRE_APPROVAL | 未知风险默认需确认 |

只有当 Tool 注册时明确声明 `side_effect_level=read_only` 且 Analyzer 确认无敏感数据外发风险时，才可降级为 ALLOW。

---

## 6. Approval 状态机

```
         create()
            │
            ▼
        PENDING ──── expires() ────→ EXPIRED
            │
      ┌─────┴─────┐
      ▼           ▼
  APPROVED     DENIED
      │
  consume()
      │
      ▼
   CONSUMED
```

状态流转：

| 当前状态 | 触发 | 目标状态 | 说明 |
|---|---|---|---|
| PENDING | 用户审批通过 | APPROVED | 记录 resolved_by, approval_scope |
| PENDING | 用户审批拒绝 | DENIED | 记录 reason |
| PENDING | 超时 | EXPIRED | 由定时任务或查询时触发 |
| PENDING | Run 取消/终止 | CANCELLED | 由 Runtime 触发 |
| APPROVED | Runtime 消费 | CONSUMED | 记录 consumed_at，幂等 |
| APPROVED | 超时 | EXPIRED | 审批通过但未消费也超时 |

终态：EXPIRED, DENIED, CANCELLED, CONSUMED
终态不可再流转。

---

## 7. ToolCall Fingerprint 与恢复校验

### Fingerprint 生成

```python
def compute_fingerprint(
    tool_name: str,
    canonical_arguments: dict[str, Any],
    capabilities: list[ResolvedCapability],
    workspace_id: str,
    run_id: str,
    session_id: str,
) -> str:
    """生成 ToolCall 的规范化指纹。"""
    import hashlib, json
    canonical = {
        "tool_name": tool_name,
        "arguments": _canonicalize(canonical_arguments),
        "capabilities": sorted([c.capability for c in capabilities]),
        "workspace_id": workspace_id,
        "run_id": run_id,
        "session_id": session_id,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
```

### 恢复校验流程

Runtime 在恢复执行时必须验证：

```python
async def validate_approval(self, approval: ApprovalRequest, tool_call: ToolCall, run: RunSnapshot) -> bool:
    # 1. 属于当前 Run
    if approval.run_id != run.run_id:
        return False
    # 2. tool_call_id 一致
    if approval.tool_call_id != tool_call.tool_call_id:
        return False
    # 3. fingerprint 一致
    expected_fp = compute_fingerprint(...)
    if approval.tool_call_fingerprint != expected_fp:
        return False
    # 4. 未过期
    if approval.expires_at and datetime.now(timezone.utc) > approval.expires_at:
        return False
    # 5. 状态为 APPROVED（未消费）
    if approval.status != ApprovalStatus.APPROVED:
        return False
    # 6. run_revision 一致
    if approval.run_revision != run.version:
        return False
    return True
```

---

## 8. Bash Parser 设计

### 复合命令拆分

BashParser 将 shell 命令解析为 ParsedAction 树：

```python
class BashParser:
    """Shell 命令解析器。"""

    # shell 操作符
    OPERATORS = {";", "&&", "||", "|"}

    # 动态执行标记（无法静态分析）
    DYNAMIC_MARKERS = ["eval", "source", "bash -c", "sh -c", "$(", "`"]

    def parse(self, tool_call: ToolCall) -> ParsedAction:
        command = tool_call.arguments.get("command", "")
        return self._parse_command(command, operator_before=None)

    def _parse_command(self, command: str, operator_before: str | None) -> ParsedAction:
        # 1. 按操作符拆分
        segments = self._split_operators(command)

        if len(segments) > 1:
            # 复合命令 → 树形结构
            children = []
            for seg in segments:
                child = self._parse_command(seg.command, seg.operator)
                children.append(child)
            return ParsedAction(
                action_id=_new_id(),
                executable=None,
                args=[],
                flags={},
                operator_before=operator_before,
                children=children,
                raw=command,
                parse_completeness=self._worst_completeness(children),
                parse_warnings=self._merge_warnings(children),
            )

        # 2. 单一命令 → 解析 executable, args, flags
        tokens = self._tokenize(command)
        executable = tokens[0] if tokens else None
        args, flags = self._parse_args(tokens[1:])

        # 3. 检测动态执行
        completeness = AnalysisCompleteness.COMPLETE
        warnings: list[str] = []
        if self._is_dynamic(executable, args):
            completeness = AnalysisCompleteness.UNKNOWN
            warnings.append(f"动态执行: {executable}")

        # 4. 检测子命令（find -exec, xargs, bash -c）
        children = self._extract_children(executable, args, flags)

        if children:
            child_completeness = self._worst_completeness(children)
            if child_completeness == AnalysisCompleteness.UNKNOWN:
                completeness = AnalysisCompleteness.UNKNOWN
            elif child_completeness == AnalysisCompleteness.PARTIAL:
                completeness = AnalysisCompleteness.PARTIAL
            warnings.extend(self._merge_warnings(children))

        return ParsedAction(
            action_id=_new_id(),
            executable=executable,
            args=args,
            flags=flags,
            operator_before=operator_before,
            children=children,
            raw=command,
            parse_completeness=completeness,
            warnings=warnings,
        )
```

### 子命令提取

```python
def _extract_children(self, executable: str, args: list[str], flags: dict) -> list[ParsedAction]:
    """提取隐式子命令。"""
    children = []

    # find -exec
    if executable == "find" and "exec" in flags:
        exec_cmd = flags["exec"].replace("{}", "").replace("\\;", "").strip()
        if exec_cmd:
            children.append(self._parse_command(exec_cmd, operator_before=None))

    # xargs
    if executable == "xargs" and args:
        children.append(self._parse_command(" ".join(args), operator_before=None))

    # bash -c / sh -c
    if executable in ("bash", "sh") and "-c" in args:
        idx = args.index("-c")
        if idx + 1 < len(args):
            children.append(self._parse_command(args[idx + 1], operator_before=None))

    return children
```

---

## 9. Bash Analyzer 设计

```python
class BashAnalyzer:
    """Shell 命令能力分析器。"""

    # 保护路径
    PROTECTED_PATHS = {
        ".git", ".env", ".ssh", ".gnupg",
        "/etc", "/boot", "/sys", "/proc",
        "~/.ssh", "~/.gnupg", "~/.aws",
    }

    # 临时/构建目录（由可信配置声明，不由模型指定）
    TEMP_DIRS = {"/tmp", "/var/tmp", "node_modules", ".cache", "dist", "build", "__pycache__"}

    def analyze(self, parsed: ParsedAction) -> CapabilityAnalysis:
        if parsed.children:
            return self._analyze_compound(parsed)
        return self._analyze_single(parsed)

    def _analyze_single(self, parsed: ParsedAction) -> CapabilityAnalysis:
        exe = parsed.executable
        warnings: list[str] = list(parsed.parse_warnings)

        # 动态执行 → UNKNOWN
        if parsed.parse_completeness == "unknown":
            return CapabilityAnalysis(
                capabilities=[ResolvedCapability(
                    capability="system.execute_dynamic",
                    metadata={"raw": parsed.raw},
                    source_action_id=parsed.action_id,
                    completeness=AnalysisCompleteness.UNKNOWN,
                    warnings=warnings,
                )],
                completeness=AnalysisCompleteness.UNKNOWN,
                warnings=warnings,
            )

        # 按 executable 分类
        if exe in ("rm", "unlink", "rmdir"):
            return self._analyze_delete(parsed, warnings)
        elif exe in ("mv", "cp", "install"):
            return self._analyze_move_copy(parsed, warnings)
        elif exe in ("cat", "less", "head", "tail", "grep", "find", "ls", "stat"):
            return self._analyze_read(parsed, warnings)
        elif exe in ("echo", "printf", "tee", "sed", "awk"):
            return self._analyze_write(parsed, warnings)
        elif exe in ("git",):
            return self._analyze_git(parsed, warnings)
        elif exe in ("curl", "wget"):
            return self._analyze_network(parsed, warnings)
        elif exe in ("chmod", "chown", "chgrp"):
            return self._analyze_permission_change(parsed, warnings)
        elif exe in ("sudo", "su"):
            return CapabilityAnalysis(
                capabilities=[ResolvedCapability(
                    capability="system.elevate",
                    metadata={"command": parsed.raw},
                    source_action_id=parsed.action_id,
                    completeness=AnalysisCompleteness.COMPLETE,
                    warnings=[],
                )],
                completeness=AnalysisCompleteness.COMPLETE,
                warnings=["提权操作"],
            )
        else:
            # 未知命令 → 按 side_effect_level 兜底（REQUIRE_APPROVAL）
            return CapabilityAnalysis(
                capabilities=[ResolvedCapability(
                    capability="system.execute_unknown",
                    metadata={"executable": exe, "raw": parsed.raw},
                    source_action_id=parsed.action_id,
                    completeness=parsed.parse_completeness,
                    warnings=warnings,
                )],
                completeness=parsed.parse_completeness,
                warnings=warnings + [f"未知命令: {exe}"],
            )
```

### 删除分析

```python
def _analyze_delete(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
    targets = parsed.args
    recursive = "-r" in parsed.flags or "-rf" in parsed.raw
    force = "-f" in parsed.flags or "-rf" in parsed.raw

    metadata = {
        "targets": targets,
        "recursive": recursive,
        "force": force,
        "target_count": len(targets),
        "workspace_relation": self._workspace_relation(targets),
        "protected_path": any(self._is_protected(t) for t in targets),
        "tracked_by_git": None,  # 需要 git 信息时填充
    }

    return CapabilityAnalysis(
        capabilities=[ResolvedCapability(
            capability="filesystem.delete",
            metadata=metadata,
            source_action_id=parsed.action_id,
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )],
        completeness=AnalysisCompleteness.COMPLETE,
        warnings=warnings,
    )
```

---

## 10. 默认规则

```python
INITIAL_RULES = [
    # ─── SYSTEM_GUARDRAIL（不可覆盖） ───
    PermissionRule(
        layer=SYSTEM_GUARDRAIL, capability="system.elevate",
        policy="deny", description="系统强制：禁止提权",
    ),
    PermissionRule(
        layer=SYSTEM_GUARDRAIL, capability="system.execute_dynamic",
        policy="require_approval", description="系统强制：动态执行需审批",
    ),

    # ─── BUILTIN_DEFAULT（可被用户规则覆盖） ───
    # 文件系统
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="filesystem.delete",
        policy="require_approval", description="删除操作默认需审批",
    ),
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="filesystem.write",
        policy="require_approval", description="写入操作默认需审批",
    ),
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="filesystem.read",
        policy="require_approval", description="读取操作默认需审批（可能泄露敏感数据）",
    ),
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="filesystem.execute",
        policy="require_approval", description="执行命令默认需审批",
    ),
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="system.execute_unknown",
        policy="require_approval", description="未知命令默认需审批",
    ),
    # 网络
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="network.request",
        policy="require_approval", description="网络请求默认需审批",
    ),
    # 仓库
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="repository.push",
        policy="require_approval", description="推送代码默认需审批",
    ),
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="repository.force_push",
        policy="deny", description="强制推送默认拒绝",
    ),
    # 记忆
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="memory.read",
        policy="auto_allow", description="读取记忆安全",
    ),
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="memory.write",
        policy="auto_allow", description="写入记忆安全",
    ),
    PermissionRule(
        layer=BUILTIN_DEFAULT, capability="memory.search",
        policy="auto_allow", description="搜索记忆安全",
    ),
]
```

注意：**不再有基于 `ls*`, `cat*`, `echo*` 等原始字符串的自动放行规则。**

---

## 11. 与 v3 的差异说明

| 项 | v3 | v3.1 |
|---|---|---|
| ParsedAction | 单层结构 | 树形 AST，支持复合命令 |
| Capability | 一对一 | 一对多（CapabilityAnalysis） |
| 完整度 | 无 | AnalysisCompleteness + fail-closed |
| 动态命令 | GenericAnalyzer 兜底 | UNKNOWN → REQUIRE_APPROVAL，不兜底 |
| 默认规则 | `ls*` 等字符串放行 | 全部 REQUIRE_APPROVAL（memory 除外） |
| arguments_pattern | 可独立生效 | 只能收紧，不能放松 |
| 规则优先级 | priority 整数 | layer → specificity → priority → tie-breaker |
| Scope | global / session | run / session / project / global + expires_at + scope_id |
| Approval 状态 | pending / approved / denied / expired / cancelled | + consumed（APPROVED → CONSUMED） |
| Approval 绑定 | 无 | tool_call_id + fingerprint + run_revision |
| Fingerprint | 无 | SHA256(tool_name + canonical_args + capabilities + workspace + run + session) |
| 恢复校验 | 无 | 6 项校验（见第 7 节） |
| 删除 metadata | outside_workspace | targets + recursive + force + target_count + workspace_relation + protected_path + tracked_by_git |
| side_effect_level | read_only → auto_allow | read_only → REQUIRE_APPROVAL |
| PermissionTrace | 单条 | 每个 Capability 独立决策 + 聚合 |

---

## 12. 模块结构

```
backend/app/permission/
├── __init__.py
├── models.py              # 所有数据模型
├── store.py               # PermissionStore + ApprovalStore (SQLite)
├── engine.py              # PermissionEngine
├── interceptor.py         # PermissionInterceptor
├── matcher.py             # Rule Matcher + conditions 匹配
├── fingerprint.py         # ToolCall fingerprint 生成与校验
├── parser/
│   ├── __init__.py
│   ├── base.py            # ToolParser Protocol, GenericParser
│   └── bash.py            # BashParser（复合命令 AST）
├── analyzer/
│   ├── __init__.py
│   ├── base.py            # CapabilityAnalyzer Protocol, GenericAnalyzer
│   └── bash.py            # BashAnalyzer（能力识别 + 风险元数据）
└── approval.py            # ApprovalManager（状态机 + 过期 + 消费）

backend/app/api/
├── permission.py          # 权限规则 API
└── approval.py            # 审批 API

backend/tests/
├── test_bash_parser.py          # 复合命令解析
├── test_bash_analyzer.py        # 能力识别 + 删除风险元数据
├── test_completeness.py         # fail-closed 策略
├── test_permission_engine.py    # 聚合决策
├── test_permission_matcher.py   # 规则匹配 + 层级 + 冲突
├── test_fingerprint.py          # fingerprint 生成 + 校验
├── test_approval_manager.py     # 状态机 + 过期 + 消费
├── test_approval_validation.py  # 恢复校验
├── test_permission_interceptor.py
├── test_pattern_constraint.py   # arguments_pattern 只能收紧
└── test_api_permission.py
```

---

## 13. 测试清单

### BashParser

| 测试点 | 说明 |
|---|---|
| 单一命令 | `rm -rf /tmp` → 正确解析 executable, args, flags |
| 复合命令（;） | `ls; rm foo` → 树形结构，两个 children |
| 复合命令（&&） | `cat a && curl b` → operator_before="&&" |
| 管道 | `cat a \| grep b` → 两个 children |
| find -exec | `find . -exec rm {} \;` → children 包含 rm |
| xargs | `echo a \| xargs rm` → children 包含 rm |
| bash -c | `bash -c "rm file"` → children 包含 rm |
| eval | `eval "$CMD"` → completeness=unknown |
| 动态输入 | `$(cat cmd)` → completeness=unknown |
| 命令注入 | `cat /etc/passwd; rm -rf /` → 拆分为两个子命令 |

### BashAnalyzer

| 测试点 | 说明 |
|---|---|
| rm 分析 | 识别 targets, recursive, force, workspace_relation |
| 保护路径 | `rm .git` → protected_path=True |
| 工作区内/外 | `/tmp/x` vs `./src/x` → workspace_relation 正确 |
| 临时目录 | `rm /tmp/x` → 可信配置中的临时目录 |
| git 操作 | `git push` → repository.push |
| curl | `curl https://x.com` → network.request |
| sudo | `sudo rm x` → system.elevate |
| 未知命令 | `unknowncmd` → system.execute_unknown |
| 动态执行 | `eval "$X"` → system.execute_dynamic, completeness=unknown |

### PermissionEngine

| 测试点 | 说明 |
|---|---|
| 单 Capability ALLOW | memory.read → auto_allow |
| 单 Capability DENY | system.elevate → deny |
| 聚合 DENY | 子命令中有一个 deny → 整体 deny |
| 聚合 REQUIRE_APPROVAL | 子命令中有一个 require_approval → 整体 require_approval |
| 聚合 ALLOW | 所有子命令 auto_allow → 整体 allow |
| PARTIAL 提升 | completeness=partial + allow → require_approval |
| UNKNOWN 拒绝 | completeness=unknown → require_approval |
| arguments_pattern 收紧 | allow 规则 + pattern deny → require_approval/deny |
| arguments_pattern 放松禁止 | deny 规则 + pattern allow → deny（不降级） |
| 规则层级优先 | SYSTEM_GUARDRAIL > USER_GLOBAL_RULE |
| 同层冲突 | deny > require_approval > allow |
| 删除 outside_workspace | filesystem.delete + outside=True → require_approval |
| 删除保护路径 | filesystem.delete + protected=True → deny |

### ApprovalManager

| 测试点 | 说明 |
|---|---|
| 创建审批 | PENDING 状态，字段完整 |
| 审批通过 | PENDING → APPROVED |
| 审批拒绝 | PENDING → DENIED |
| 过期 | PENDING → EXPIRED |
| 取消 | PENDING → CANCELLED |
| 消费 | APPROVED → CONSUMED |
| 重复消费 | CONSUMED 状态再消费 → 幂等 |
| 终态不可流转 | EXPIRED/DENIED/CANCELLED/CONSUMED 不能再变 |
| fingerprint 绑定 | 不同 fingerprint 不能复用审批 |

### Approval Validation（恢复校验）

| 测试点 | 说明 |
|---|---|
| 校验通过 | 所有条件满足 → True |
| run_id 不匹配 | False |
| tool_call_id 不匹配 | False |
| fingerprint 不匹配 | False |
| 已过期 | False |
| 状态非 APPROVED | False |
| run_revision 不匹配 | False |

### PermissionInterceptor

| 测试点 | 说明 |
|---|---|
| ALLOW → Allow() | 正常通过 |
| DENY → Reject() | 返回拒绝原因 |
| REQUIRE_APPROVAL → SuspendDecision() | 创建审批，返回 approval_id |

---

## 14. 确认

- [ ] 设计评审通过
- [ ] 可以开始编码
