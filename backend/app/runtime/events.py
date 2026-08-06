"""Runtime Event 模型。

类型化 discriminated union 事件体系，借鉴 PydanticAI 事件模型。
Agent Loop 通过发布事件驱动状态变更通知、流式推送和持久化。

事件分四类：
- Run 生命周期事件（持久化）
- 模型事件（部分持久化，delta 类仅实时推送）
- 工具事件（部分持久化，progress 仅实时推送）
- 系统事件（持久化）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from app.runtime.models import EventId, Usage, new_event_id


# ─── 事件类型枚举 ─────────────────────────────────────────


class EventType(str, Enum):
    """所有事件类型的枚举。"""

    # Run 生命周期
    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    RUN_STATE_CHANGED = "run_state_changed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_SUSPENDED = "run_suspended"
    RUN_RESUMED = "run_resumed"
    RUN_CANCELLATION_REQUESTED = "run_cancellation_requested"
    RUN_CANCELLED = "run_cancelled"
    RUN_TERMINATED = "run_terminated"

    # 模型事件
    MODEL_REQUEST_STARTED = "model_request_started"
    MODEL_TEXT_DELTA = "model_text_delta"
    MODEL_REASONING_DELTA = "model_reasoning_delta"
    MODEL_TOOL_CALL_DELTA = "model_tool_call_delta"
    MODEL_RESPONSE_COMPLETED = "model_response_completed"

    # 工具事件
    TOOL_CALL_PROPOSED = "tool_call_proposed"
    TOOL_CALL_MODIFIED = "tool_call_modified"
    TOOL_APPROVAL_REQUESTED = "tool_approval_requested"
    TOOL_EXECUTION_STARTED = "tool_execution_started"
    TOOL_EXECUTION_PROGRESS = "tool_execution_progress"
    TOOL_EXECUTION_COMPLETED = "tool_execution_completed"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"

    # 系统事件
    CHECKPOINT_CREATED = "checkpoint_created"
    USAGE_UPDATED = "usage_updated"
    ARTIFACT_CREATED = "artifact_created"


# ─── 事件基类 ─────────────────────────────────────────────


@dataclass
class RuntimeEvent:
    """运行时事件基类。

    所有具体事件类型继承此类。
    persisted 类变量标记该事件是否需要写入持久化存储：
    True 表示需要持久化（写入 EventStore）；
    False 表示仅实时推送（如 token delta、进度更新）。
    """

    event_id: str
    run_id: str
    session_id: str
    sequence: int
    timestamp: datetime
    event_type: EventType
    schema_version: int = 1
    causal_parent_id: str | None = None
    execution_attempt: int = 0

    # 子类覆盖：True = 持久化，False = 仅实时推送
    persisted: bool = True

    def __post_init__(self) -> None:
        if not self.timestamp.tzinfo:
            object.__setattr__(
                self, "timestamp", self.timestamp.replace(tzinfo=timezone.utc)
            )


# ─── Run 生命周期事件 ──────────────────────────────────────


@dataclass
class RunCreated(RuntimeEvent):
    """Run 已创建。"""

    event_type: Literal[EventType.RUN_CREATED] = EventType.RUN_CREATED
    agent_id: str = ""
    metadata: dict[str, Any] | None = None


@dataclass
class RunStarted(RuntimeEvent):
    """Run 开始执行。"""

    event_type: Literal[EventType.RUN_STARTED] = EventType.RUN_STARTED
    max_steps: int = 0


@dataclass
class RunStateChanged(RuntimeEvent):
    """Run 状态变更。"""

    event_type: Literal[EventType.RUN_STATE_CHANGED] = EventType.RUN_STATE_CHANGED
    old_status: str = ""
    new_status: str = ""


@dataclass
class RunCompleted(RuntimeEvent):
    """Run 正常完成。"""

    event_type: Literal[EventType.RUN_COMPLETED] = EventType.RUN_COMPLETED
    output: Any = None
    usage: Usage | None = None


@dataclass
class RunFailed(RuntimeEvent):
    """Run 不可恢复错误。"""

    event_type: Literal[EventType.RUN_FAILED] = EventType.RUN_FAILED
    error_type: str = ""
    error_message: str = ""
    is_retryable: bool = False


@dataclass
class RunSuspended(RuntimeEvent):
    """Run 暂停等待外部输入。"""

    event_type: Literal[EventType.RUN_SUSPENDED] = EventType.RUN_SUSPENDED
    suspension_id: str = ""
    suspension_type: str = ""
    reason: str = ""


@dataclass
class RunResumed(RuntimeEvent):
    """Run 从暂停恢复。"""

    event_type: Literal[EventType.RUN_RESUMED] = EventType.RUN_RESUMED
    suspension_id: str = ""
    idempotency_key: str = ""


@dataclass
class RunCancellationRequested(RuntimeEvent):
    """Run 取消请求已接收。"""

    event_type: Literal[EventType.RUN_CANCELLATION_REQUESTED] = (
        EventType.RUN_CANCELLATION_REQUESTED
    )
    reason: str | None = None


@dataclass
class RunCancelled(RuntimeEvent):
    """Run 已取消。"""

    event_type: Literal[EventType.RUN_CANCELLED] = EventType.RUN_CANCELLED
    reason: str | None = None


@dataclass
class RunTerminated(RuntimeEvent):
    """Run 已硬杀。"""

    event_type: Literal[EventType.RUN_TERMINATED] = EventType.RUN_TERMINATED
    reason: str = ""


# ─── 模型事件 ──────────────────────────────────────────────


@dataclass
class ModelRequestStarted(RuntimeEvent):
    """模型请求已发出。"""

    event_type: Literal[EventType.MODEL_REQUEST_STARTED] = (
        EventType.MODEL_REQUEST_STARTED
    )
    model: str = ""
    step: int = 0


@dataclass
class ModelTextDelta(RuntimeEvent):
    """Token delta，不持久化。"""

    event_type: Literal[EventType.MODEL_TEXT_DELTA] = EventType.MODEL_TEXT_DELTA
    delta: str = ""
    content_index: int = 0
    persisted: bool = False


@dataclass
class ModelReasoningDelta(RuntimeEvent):
    """推理 delta，不持久化。"""

    event_type: Literal[EventType.MODEL_REASONING_DELTA] = (
        EventType.MODEL_REASONING_DELTA
    )
    delta: str = ""
    persisted: bool = False


@dataclass
class ModelToolCallDelta(RuntimeEvent):
    """工具调用参数 delta，不持久化。"""

    event_type: Literal[EventType.MODEL_TOOL_CALL_DELTA] = (
        EventType.MODEL_TOOL_CALL_DELTA
    )
    tool_call_id: str = ""
    arguments_delta: str = ""
    persisted: bool = False


@dataclass
class ModelResponseCompleted(RuntimeEvent):
    """模型响应完成。"""

    event_type: Literal[EventType.MODEL_RESPONSE_COMPLETED] = (
        EventType.MODEL_RESPONSE_COMPLETED
    )
    finish_reason: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    usage: Usage | None = None


# ─── 工具事件 ──────────────────────────────────────────────


@dataclass
class ToolCallProposed(RuntimeEvent):
    """模型提议的工具调用。"""

    event_type: Literal[EventType.TOOL_CALL_PROPOSED] = EventType.TOOL_CALL_PROPOSED
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] | None = None


@dataclass
class ToolCallModified(RuntimeEvent):
    """拦截器修改了工具调用参数。"""

    event_type: Literal[EventType.TOOL_CALL_MODIFIED] = EventType.TOOL_CALL_MODIFIED
    tool_call_id: str = ""
    original_arguments: dict[str, Any] | None = None
    modified_arguments: dict[str, Any] | None = None
    modified_by: str = ""  # 拦截器名称


@dataclass
class ToolApprovalRequested(RuntimeEvent):
    """工具审批请求。"""

    event_type: Literal[EventType.TOOL_APPROVAL_REQUESTED] = (
        EventType.TOOL_APPROVAL_REQUESTED
    )
    suspension_id: str = ""
    approval_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] | None = None
    reason: str = ""


@dataclass
class ToolExecutionStarted(RuntimeEvent):
    """工具开始执行。"""

    event_type: Literal[EventType.TOOL_EXECUTION_STARTED] = (
        EventType.TOOL_EXECUTION_STARTED
    )
    tool_call_id: str = ""
    tool_name: str = ""
    execution_id: str = ""


@dataclass
class ToolExecutionProgress(RuntimeEvent):
    """工具执行进度，不持久化。"""

    event_type: Literal[EventType.TOOL_EXECUTION_PROGRESS] = (
        EventType.TOOL_EXECUTION_PROGRESS
    )
    tool_call_id: str = ""
    execution_id: str = ""
    progress: float = 0.0
    total: float | None = None
    message: str | None = None
    persisted: bool = False


@dataclass
class ToolExecutionCompleted(RuntimeEvent):
    """工具执行完成。"""

    event_type: Literal[EventType.TOOL_EXECUTION_COMPLETED] = (
        EventType.TOOL_EXECUTION_COMPLETED
    )
    tool_call_id: str = ""
    tool_name: str = ""
    execution_id: str = ""
    is_error: bool = False
    duration_ms: float = 0.0


@dataclass
class ToolExecutionFailed(RuntimeEvent):
    """工具执行失败。"""

    event_type: Literal[EventType.TOOL_EXECUTION_FAILED] = (
        EventType.TOOL_EXECUTION_FAILED
    )
    tool_call_id: str = ""
    tool_name: str = ""
    execution_id: str = ""
    error_type: str = ""
    error_message: str = ""


# ─── 系统事件 ──────────────────────────────────────────────


@dataclass
class CheckpointCreated(RuntimeEvent):
    """检查点已创建。"""

    event_type: Literal[EventType.CHECKPOINT_CREATED] = EventType.CHECKPOINT_CREATED
    checkpoint_id: str = ""
    step: int = 0


@dataclass
class UsageUpdated(RuntimeEvent):
    """使用量已更新。"""

    event_type: Literal[EventType.USAGE_UPDATED] = EventType.USAGE_UPDATED
    usage: Usage | None = None


@dataclass
class ArtifactCreated(RuntimeEvent):
    """制品已创建。"""

    event_type: Literal[EventType.ARTIFACT_CREATED] = EventType.ARTIFACT_CREATED
    artifact_id: str = ""
    artifact_type: str = ""
    name: str = ""
    path: str | None = None


# ─── 联合类型 ──────────────────────────────────────────────

RuntimeEventUnion = (
    RunCreated
    | RunStarted
    | RunStateChanged
    | RunCompleted
    | RunFailed
    | RunSuspended
    | RunResumed
    | RunCancellationRequested
    | RunCancelled
    | RunTerminated
    | ModelRequestStarted
    | ModelTextDelta
    | ModelReasoningDelta
    | ModelToolCallDelta
    | ModelResponseCompleted
    | ToolCallProposed
    | ToolCallModified
    | ToolApprovalRequested
    | ToolExecutionStarted
    | ToolExecutionProgress
    | ToolExecutionCompleted
    | ToolExecutionFailed
    | CheckpointCreated
    | UsageUpdated
    | ArtifactCreated
)


# ─── 事件工厂函数 ─────────────────────────────────────────


def create_event(event_cls: type, run_id: str, session_id: str, sequence: int, **kwargs: Any) -> RuntimeEvent:
    """创建事件实例的便捷工厂。

    自动填充 event_id 和 timestamp，调用方只需提供业务字段。
    """
    return event_cls(
        event_id=new_event_id(),
        run_id=run_id,
        session_id=session_id,
        sequence=sequence,
        timestamp=datetime.now(timezone.utc),
        **kwargs,
    )
