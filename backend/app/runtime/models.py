"""Runtime Adapter 核心领域模型。

所有 Runtime Adapter 层共用的类型定义。
标识符使用 NewType 包装的 str，兼顾类型安全和序列化便利。
核心模型使用 dataclass；API 请求/响应用 Pydantic。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, NewType

from pydantic import BaseModel, Field

# ─── 标识符 ───────────────────────────────────────────────

RunId = NewType("RunId", str)
SessionId = NewType("SessionId", str)
EventId = NewType("EventId", str)
ToolExecutionId = NewType("ToolExecutionId", str)
SuspensionId = NewType("SuspensionId", str)


def new_run_id() -> RunId:
    """生成唯一 Run ID。"""
    return RunId(str(uuid.uuid4()))


def new_event_id() -> EventId:
    """生成唯一事件 ID。"""
    return EventId(str(uuid.uuid4()))


def new_suspension_id() -> SuspensionId:
    """生成唯一暂停 ID。"""
    return SuspensionId(str(uuid.uuid4()))


def new_tool_execution_id() -> ToolExecutionId:
    """生成唯一工具执行 ID。"""
    return ToolExecutionId(str(uuid.uuid4()))


# ─── 枚举 ─────────────────────────────────────────────────


class RunStatus(str, Enum):
    """Run 生命周期状态。"""

    CREATED = "created"           # 已创建，尚未执行
    QUEUED = "queued"             # 等待调度
    RUNNING = "running"           # Agent Loop 正在执行
    WAITING = "waiting"           # 等待外部输入（审批等）
    RESUMING = "resuming"         # 正在恢复执行
    COMPLETED = "completed"       # 正常完成
    FAILED = "failed"             # 不可恢复错误
    CANCELLING = "cancelling"     # 正在取消
    CANCELLED = "cancelled"       # 已取消
    TERMINATED = "terminated"     # 已硬杀


class SuspensionType(str, Enum):
    """暂停类型——为什么暂停。"""

    TOOL_APPROVAL = "tool_approval"           # 工具需要用户审批
    MISSING_INPUT = "missing_input"           # 缺少必要输入
    EXTERNAL_CALLBACK = "external_callback"   # 等待外部系统回调
    POLICY_ESCALATION = "policy_escalation"   # 策略升级需要人工介入
    TOOL_UNAVAILABLE = "tool_unavailable"     # 工具暂时不可用


class SideEffectLevel(str, Enum):
    """工具副作用等级。"""

    READ_ONLY = "read_only"                    # 只读，无副作用
    LOCAL_MUTATION = "local_mutation"          # 本地状态变更（可回滚）
    EXTERNAL_MUTATION = "external_mutation"    # 外部系统变更（难以回滚）
    IRREVERSIBLE = "irreversible"              # 不可逆操作


class SuspensionCapability(str, Enum):
    """暂停能力等级。"""

    NONE = "none"                                    # 不支持暂停
    IN_PROCESS = "in_process"                        # 进程内暂停（协程存活）
    CHECKPOINTED_RESTART = "checkpointed_restart"    # 可 checkpoint 后重启恢复
    DURABLE_REPLAY = "durable_replay"                # 可跨服务重启恢复（如 Temporal）


class CancellationCapability(str, Enum):
    """取消能力等级。"""

    NONE = "none"
    COOPERATIVE = "cooperative"    # 协作式取消（传递 CancellationToken）
    IMMEDIATE = "immediate"        # 立即取消


class EventDeliveryGuarantee(str, Enum):
    """事件投递保证。"""

    BEST_EFFORT = "best_effort"
    AT_LEAST_ONCE = "at_least_once"


class Role(str, Enum):
    """消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# ─── Run 请求与句柄 ────────────────────────────────────────


class RunRequest(BaseModel):
    """创建 Run 的请求。"""

    session_id: SessionId
    agent_id: str
    messages: list[Message] = Field(default_factory=list)
    tools: list[ToolDef] = Field(default_factory=list)
    max_steps: int = 20
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class RunHandle:
    """Run 创建后返回的句柄。"""

    run_id: RunId
    status: RunStatus
    created_at: datetime


@dataclass
class RunSnapshot:
    """Run 的完整状态快照，用于 checkpoint 和恢复。"""

    run_id: RunId
    session_id: SessionId
    agent_id: str
    status: RunStatus
    version: int                       # 乐观锁版本号
    messages: list[Message]            # 完整消息历史
    current_step: int                  # 当前步骤号
    max_steps: int                     # 最大步骤数
    usage: Usage                       # Token 使用量
    suspension_id: SuspensionId | None # 当前暂停 ID（WAITING 状态时有值）
    execution_attempt: int             # 当前执行尝试次数
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    metadata: dict[str, Any]


# ─── 消息与内容 ────────────────────────────────────────────


@dataclass
class TextPart:
    """纯文本内容块。"""

    type: Literal["text"] = "text"
    text: str = ""


@dataclass
class ThinkingPart:
    """模型推理内容块。"""

    type: Literal["thinking"] = "thinking"
    thinking: str = ""


@dataclass
class ToolCallPart:
    """模型请求的工具调用。"""

    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultPart:
    """工具执行结果。"""

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    tool_name: str = ""
    content: list[ContentPart] = field(default_factory=list)
    is_error: bool = False


@dataclass
class ImagePart:
    """图片内容（base64 编码）。"""

    type: Literal["image"] = "image"
    data: str = ""
    mime_type: str = ""


# 内容块联合类型
ContentPart = TextPart | ThinkingPart | ToolCallPart | ToolResultPart | ImagePart


@dataclass
class Message:
    """对话消息。"""

    role: Role
    content: str | list[ContentPart]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── 工具 ─────────────────────────────────────────────────


@dataclass
class ToolDef:
    """工具定义——发送给模型的工具描述。"""

    name: str
    description: str
    parameters: dict[str, Any]    # JSON Schema 格式的参数定义
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY
    timeout: float | None = None  # 超时秒数
    max_retries: int = 0          # 最大重试次数
    requires_approval: bool = False  # 是否需要用户审批
    sequential: bool = False      # 是否必须串行执行


@dataclass
class ToolCall:
    """模型请求的一次工具调用。"""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """工具执行的结果。"""

    tool_call_id: str
    tool_name: str
    content: list[ContentPart] = field(default_factory=list)
    is_error: bool = False
    usage: Usage | None = None    # 工具内部的 LLM 调用 usage


@dataclass
class ToolExecution:
    """工具执行的持久化记录。"""

    execution_id: ToolExecutionId
    run_id: RunId
    tool_call: ToolCall
    status: str                   # pending | running | completed | failed | cancelled
    result: ToolResult | None
    started_at: datetime | None
    completed_at: datetime | None
    attempt: int = 1


# ─── 拦截器决策与暂停 ──────────────────────────────────────


@dataclass
class Allow:
    """拦截器决策：允许执行。"""

    type: Literal["allow"] = "allow"


@dataclass
class Modify:
    """拦截器决策：修改参数后执行。"""

    type: Literal["modify"] = "modify"
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Reject:
    """拦截器决策：拒绝执行，将原因反馈给模型。"""

    type: Literal["reject"] = "reject"
    reason: str = ""


@dataclass
class Replace:
    """拦截器决策：跳过执行，使用提供的结果替代。"""

    type: Literal["replace"] = "replace"
    result: ToolResult = field(default_factory=lambda: ToolResult("", ""))


@dataclass
class SuspendDecision:
    """拦截器决策：暂停 Run，等待外部输入。"""

    type: Literal["suspend"] = "suspend"
    request: SuspendRequest = field(
        default_factory=lambda: SuspendRequest(
            SuspensionType.TOOL_APPROVAL, ToolCall("", "", {})
        )
    )


# 拦截器决策联合类型
ToolDecision = Allow | Modify | Reject | Replace | SuspendDecision


@dataclass
class SuspendRequest:
    """暂停请求——描述为什么需要暂停。"""

    suspension_type: SuspensionType
    tool_call: ToolCall
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Suspension:
    """暂停的持久化记录。"""

    suspension_id: SuspensionId
    run_id: RunId
    suspension_type: SuspensionType
    tool_call: ToolCall
    reason: str
    status: str                   # pending | resolved | expired | cancelled
    created_at: datetime
    resolved_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResumeInput:
    """恢复暂停 Run 时提供的输入。"""

    approved: bool               # 是否批准
    idempotency_key: str         # 幂等键，防止重复恢复
    result: ToolResult | None = None   # 批准时提供工具结果
    reason: str | None = None          # 拒绝时提供原因


# ─── 运行时能力 ────────────────────────────────────────────


@dataclass
class RuntimeCapabilities:
    """Runtime 实现声明的能力。"""

    streaming: bool = True
    semantic_events: bool = True
    parallel_tool_calls: bool = True
    blocking_interceptors: bool = True
    suspension: SuspensionCapability = SuspensionCapability.IN_PROCESS
    cancellation: CancellationCapability = CancellationCapability.COOPERATIVE
    event_delivery: EventDeliveryGuarantee = EventDeliveryGuarantee.AT_LEAST_ONCE
    checkpoint: bool = True
    external_resume: bool = False
    session_persistence: bool = True
    event_replay: bool = True
    model_cancellation: bool = True
    tool_cancellation: bool = True
    run_cancellation: bool = True
    termination: bool = True


# ─── 使用量 ────────────────────────────────────────────────


@dataclass
class Usage:
    """Token 和费用使用量。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    cost: float = 0.0

    def add(self, other: Usage) -> None:
        """累加另一个 Usage 的值。"""
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.total_tokens += other.total_tokens
        self.requests += other.requests
        self.cost += other.cost


# ─── Checkpoint ────────────────────────────────────────────


@dataclass
class PendingWrite:
    """已产生但尚未应用的写入。"""

    task_id: str
    channel: str
    value: Any


@dataclass
class Checkpoint:
    """Run 在步骤边界的持久化快照。"""

    id: str
    run_id: RunId
    step: int
    state: RunSnapshot
    pending_writes: list[PendingWrite]
    timestamp: datetime
    schema_version: int = 1


# ─── 执行尝试 ─────────────────────────────────────────────


@dataclass
class ExecutionAttempt:
    """一次执行尝试（可能跨越多个步骤）。"""

    attempt_id: str
    run_id: RunId
    started_at: datetime
    completed_at: datetime | None
    status: str                   # running | completed | failed
    error: str | None = None


# ─── 取消令牌 ──────────────────────────────────────────────


class CancellationToken:
    """协作式取消令牌。

    传递给 LiteLLMClient 和 ToolExecutor，用于传播取消信号。
    基于 asyncio.Event 实现，线程安全。
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason: str = ""

    def cancel(self, reason: str = "") -> None:
        """发出取消信号。"""
        self._reason = reason
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """是否已取消。"""
        return self._event.is_set()

    @property
    def reason(self) -> str:
        """取消原因。"""
        return self._reason

    async def wait(self) -> None:
        """等待取消信号。用于 async 场景下检查是否被取消。"""
        await self._event.wait()

    async def raise_if_cancelled(self) -> None:
        """如果已取消则抛出 asyncio.CancelledError。"""
        if self.is_cancelled:
            raise asyncio.CancelledError(self._reason or "操作已取消")
