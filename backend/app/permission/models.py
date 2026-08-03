"""Permission 模块数据模型。

设计要点：
- ParsedAction 支持复合命令 AST + 重定向
- AnalysisCompleteness + fail-closed 策略
- 规则层级（SYSTEM_GUARDRAIL > SESSION_OVERRIDE > PROJECT_RULE > USER_GLOBAL_RULE > BUILTIN_DEFAULT）
- Approval 状态机 + 原子执行 claim
- fingerprint 包含 capability metadata
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── 标识符 ───────────────────────────────────────────────


def new_rule_id() -> str:
    return str(uuid.uuid4())


def new_approval_id() -> str:
    return str(uuid.uuid4())


def new_action_id() -> str:
    return str(uuid.uuid4())


# ─── 枚举 ─────────────────────────────────────────────────


class PermissionResult(str, Enum):
    """权限决策结果。"""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class AnalysisCompleteness(str, Enum):
    """分析完整度——决定 fail-closed 策略。"""
    COMPLETE = "complete"      # 所有子命令均已完整解析
    PARTIAL = "partial"        # 部分子命令无法完整解析
    UNKNOWN = "unknown"        # 无法解析（eval, bash -c, 动态输入）


class PermissionRuleLayer(str, Enum):
    """规则层级——决定冲突时的优先顺序。"""
    SYSTEM_GUARDRAIL = "system_guardrail"      # 系统强制规则，不可被覆盖
    SESSION_OVERRIDE = "session_override"      # 本次会话覆盖（审批时生成）
    PROJECT_RULE = "project_rule"              # 项目级规则
    USER_GLOBAL_RULE = "user_global_rule"      # 用户全局规则
    BUILTIN_DEFAULT = "builtin_default"        # 内置默认规则


class PermissionScope(str, Enum):
    """规则作用范围。"""
    RUN = "run"
    SESSION = "session"
    PROJECT = "project"
    GLOBAL = "global"


class ApprovalStatus(str, Enum):
    """审批状态机。"""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    CONSUMED = "consumed"

    @property
    def is_terminal(self) -> bool:
        return self in (
            ApprovalStatus.EXPIRED,
            ApprovalStatus.DENIED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.CONSUMED,
        )


# ─── ParsedAction（复合命令 AST）──────────────────────────


@dataclass
class Redirection:
    """Shell 重定向。"""
    fd: int | None           # 文件描述号（None = 默认 0/1）
    operator: str            # ">", ">>", "<", ">&", "<&", "<<", "<<<", "|"
    target: str              # 目标文件或 fd


@dataclass
class ParsedAction:
    """结构化动作——支持复合命令的树形结构。

    使用 shell AST 解析，不做手写字符串切分。
    """
    action_id: str
    executable: str | None               # 可执行文件名
    args: list[str]                      # 位置参数
    flags: dict[str, Any]                # 选项参数（-f, --force 等）
    redirections: list[Redirection]      # 重定向
    operator_before: str | None          # 前置操作符（";", "&&", "||", "|", "`", "$("）
    children: list["ParsedAction"]       # 子命令
    raw: str                             # 原始字符串

    # ─── 解析元数据 ───
    parse_completeness: AnalysisCompleteness
    parse_warnings: list[str]


# ─── ResolvedCapability ───────────────────────────────────


@dataclass
class ResolvedCapability:
    """解析出的能力。"""
    capability: str                # 能力标识，如 "filesystem.delete"
    metadata: dict[str, Any]       # 风险元数据
    source_action_id: str          # 来源 ParsedAction 的 ID
    completeness: AnalysisCompleteness
    warnings: list[str]


@dataclass
class CapabilityAnalysis:
    """一次 ToolCall 的完整能力分析。"""
    capabilities: list[ResolvedCapability]
    completeness: AnalysisCompleteness    # 取所有子分析中最差的
    warnings: list[str]


# ─── PermissionRule ───────────────────────────────────────


@dataclass
class PermissionRule:
    """权限规则。"""
    rule_id: str
    layer: PermissionRuleLayer
    # ─── 匹配条件 ───
    capability: str | None
    tool_name: str | None
    arguments_pattern: str | None    # 辅助匹配，只能收紧不能放松
    conditions: dict[str, Any]       # 扩展条件（workspace, path 等）
    # ─── 决策 ───
    policy: PermissionResult
    priority: int                    # 同层内排序
    scope_type: PermissionScope
    scope_id: str | None
    expires_at: datetime | None
    created_by: str | None           # "system" | "user" | approval_id
    description: str
    created_at: datetime
    updated_at: datetime


# ─── PermissionDecision ───────────────────────────────────


@dataclass
class CapabilityDecision:
    """单个 Capability 的决策。"""
    capability: str
    result: PermissionResult
    matched_rule: PermissionRule | None
    reason: str


@dataclass
class PermissionTrace:
    """权限决策追踪。"""
    result: PermissionResult
    capability_decisions: list[CapabilityDecision]
    aggregated_reason: str
    completeness: AnalysisCompleteness
    warnings: list[str]


@dataclass
class PermissionDecision:
    """权限决策结果。"""
    result: PermissionResult
    trace: PermissionTrace


# ─── ApprovalRequest ──────────────────────────────────────


@dataclass
class ExecutionClaim:
    """原子执行声明——审批后绑定的不可变执行承诺。"""
    claim_id: str                    # 唯一 ID
    approval_id: str                 # 关联审批
    run_id: str
    tool_call_id: str
    tool_call_fingerprint: str       # 包含 capability metadata
    frozen_arguments: dict[str, Any] # 冻结的参数
    frozen_capabilities: list[ResolvedCapability]
    run_version: int                 # 创建时的 Run version
    execution_revision: int          # 执行修订号（每次 resume +1）
    created_at: datetime
    expires_at: datetime | None
    consumed_at: datetime | None


@dataclass
class ApprovalRequest:
    """审批请求。"""
    approval_id: str
    run_id: str
    session_id: str
    tool_call_id: str
    tool_call_fingerprint: str
    # ─── 审批内容 ───
    tool_name: str
    tool_arguments: dict[str, Any]
    capabilities: list[ResolvedCapability]
    trace: PermissionTrace
    # ─── 状态 ───
    status: ApprovalStatus
    run_version: int
    execution_revision: int
    # ─── 时间 ───
    created_at: datetime
    expires_at: datetime | None
    resolved_at: datetime | None
    consumed_at: datetime | None
    # ─── 审批信息 ───
    resolved_by: str | None
    approval_scope: PermissionScope | None
    reason: str | None


# ─── Fingerprint ──────────────────────────────────────────


@dataclass
class ToolCallFingerprint:
    """ToolCall 规范化指纹。"""
    tool_name: str
    canonical_arguments: dict[str, Any]
    capability_metadata: list[dict[str, Any]]  # 包含每个 capability 的 metadata
    workspace_id: str
    run_id: str
    session_id: str


# ─── Pydantic 模型（API 请求/响应）─────────────────────────


class CreatePermissionRequest(BaseModel):
    """创建权限规则请求。"""
    capability: str | None = None
    tool_name: str | None = None
    arguments_pattern: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    policy: str
    priority: int = 0
    scope_type: str = PermissionScope.GLOBAL.value
    scope_id: str | None = None
    description: str = ""


class UpdatePermissionRequest(BaseModel):
    """更新权限规则请求。"""
    policy: str | None = None
    priority: int | None = None
    conditions: dict[str, Any] | None = None
    description: str | None = None


class PermissionRuleResponse(BaseModel):
    """权限规则响应。"""
    rule_id: str
    layer: str
    capability: str | None = None
    tool_name: str | None = None
    arguments_pattern: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    policy: str
    priority: int
    scope_type: str
    scope_id: str | None = None
    expires_at: datetime | None = None
    created_by: str | None = None
    description: str
    created_at: datetime
    updated_at: datetime


class PermissionListResponse(BaseModel):
    """权限规则列表响应。"""
    rules: list[PermissionRuleResponse]
    total: int


class ApprovalRequestResponse(BaseModel):
    """审批请求响应。"""
    approval_id: str
    run_id: str
    tool_call_id: str
    tool_name: str
    tool_arguments: dict[str, Any]
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    resolved_at: datetime | None = None
    reason: str | None = None


class ApprovalListResponse(BaseModel):
    """审批列表响应。"""
    approvals: list[ApprovalRequestResponse]
    total: int


class ResolveApprovalRequest(BaseModel):
    """审批操作请求。"""
    approved: bool
    scope: str = PermissionScope.SESSION.value
    reason: str | None = None


# ─── 常量 ─────────────────────────────────────────────────

# 保护路径
PROTECTED_PATHS: set[str] = {
    ".git", ".env", ".ssh", ".gnupg",
    "/etc", "/boot", "/sys", "/proc",
    "~/.ssh", "~/.gnupg", "~/.aws",
}

# 临时/构建目录（由可信配置声明）
TEMP_DIRS: set[str] = {
    "/tmp", "/var/tmp", "node_modules", ".cache",
    "dist", "build", "__pycache__", ".pytest_cache",
}

# Shell 操作符
SHELL_OPERATORS: set[str] = {";", "&&", "||", "|"}

# 动态执行标记
DYNAMIC_MARKERS: list[str] = [
    "eval", "source", ".", "bash -c", "sh -c",
    "$(", "`", "xargs",
]
