"""RuntimeEvent 事件模型测试。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.runtime.events import (
    ArtifactCreated,
    CheckpointCreated,
    EventType,
    ModelReasoningDelta,
    ModelRequestStarted,
    ModelResponseCompleted,
    ModelTextDelta,
    ModelToolCallDelta,
    RunCancelled,
    RunCancellationRequested,
    RunCompleted,
    RunCreated,
    RunFailed,
    RunResumed,
    RunStarted,
    RunStateChanged,
    RunSuspended,
    RunTerminated,
    RuntimeEvent,
    RuntimeEventUnion,
    ToolApprovalRequested,
    ToolCallModified,
    ToolCallProposed,
    ToolExecutionCompleted,
    ToolExecutionFailed,
    ToolExecutionProgress,
    ToolExecutionStarted,
    UsageUpdated,
    create_event,
)
from app.runtime.models import Usage


# ─── 辅助 ─────────────────────────────────────────────────


def _base_kwargs() -> dict:
    """构造事件基类必填字段。"""
    return {
        "event_id": "evt-001",
        "run_id": "run-001",
        "session_id": "sess-001",
        "sequence": 1,
        "timestamp": datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc),
    }


# ─── EventType 枚举 ───────────────────────────────────────


class TestEventType:
    def test_run_lifecycle_events_exist(self) -> None:
        assert EventType.RUN_CREATED == "run_created"
        assert EventType.RUN_STARTED == "run_started"
        assert EventType.RUN_STATE_CHANGED == "run_state_changed"
        assert EventType.RUN_COMPLETED == "run_completed"
        assert EventType.RUN_FAILED == "run_failed"
        assert EventType.RUN_SUSPENDED == "run_suspended"
        assert EventType.RUN_RESUMED == "run_resumed"
        assert EventType.RUN_CANCELLATION_REQUESTED == "run_cancellation_requested"
        assert EventType.RUN_CANCELLED == "run_cancelled"
        assert EventType.RUN_TERMINATED == "run_terminated"

    def test_model_events_exist(self) -> None:
        assert EventType.MODEL_REQUEST_STARTED == "model_request_started"
        assert EventType.MODEL_TEXT_DELTA == "model_text_delta"
        assert EventType.MODEL_REASONING_DELTA == "model_reasoning_delta"
        assert EventType.MODEL_TOOL_CALL_DELTA == "model_tool_call_delta"
        assert EventType.MODEL_RESPONSE_COMPLETED == "model_response_completed"

    def test_tool_events_exist(self) -> None:
        assert EventType.TOOL_CALL_PROPOSED == "tool_call_proposed"
        assert EventType.TOOL_CALL_MODIFIED == "tool_call_modified"
        assert EventType.TOOL_APPROVAL_REQUESTED == "tool_approval_requested"
        assert EventType.TOOL_EXECUTION_STARTED == "tool_execution_started"
        assert EventType.TOOL_EXECUTION_PROGRESS == "tool_execution_progress"
        assert EventType.TOOL_EXECUTION_COMPLETED == "tool_execution_completed"
        assert EventType.TOOL_EXECUTION_FAILED == "tool_execution_failed"

    def test_system_events_exist(self) -> None:
        assert EventType.CHECKPOINT_CREATED == "checkpoint_created"
        assert EventType.USAGE_UPDATED == "usage_updated"
        assert EventType.ARTIFACT_CREATED == "artifact_created"

    def test_total_event_types(self) -> None:
        """确认 25 种事件类型（10 run + 5 model + 7 tool + 3 system）。"""
        assert len(EventType) == 25


# ─── RuntimeEvent 基类 ────────────────────────────────────


class TestRuntimeEvent:
    def test_timestamp_auto_utc(self) -> None:
        """无时区输入自动补 UTC。"""
        naive = datetime(2026, 7, 31, 12, 0, 0)  # 无时区
        base = _base_kwargs()
        base["timestamp"] = naive
        # 用 RunCreated 做测试，因为 RuntimeEvent 是抽象基类
        event = RunCreated(**base)
        assert event.timestamp.tzinfo == timezone.utc

    def test_timestamp_preserves_utc(self) -> None:
        """有时区的输入不被修改。"""
        tz_plus8 = timezone(timedelta(hours=8))
        dt = datetime(2026, 7, 31, 20, 0, 0, tzinfo=tz_plus8)
        base = _base_kwargs()
        base["timestamp"] = dt
        event = RunCreated(**base)
        assert event.timestamp.tzinfo == tz_plus8
        assert event.timestamp.hour == 20

    def test_persisted_default_true(self) -> None:
        """默认 persisted=True。"""
        event = RunCreated(**_base_kwargs())
        assert event.persisted is True

    def test_default_schema_version(self) -> None:
        event = RunCreated(**_base_kwargs())
        assert event.schema_version == 1

    def test_default_causal_parent_id_none(self) -> None:
        event = RunCreated(**_base_kwargs())
        assert event.causal_parent_id is None

    def test_default_execution_attempt_zero(self) -> None:
        event = RunCreated(**_base_kwargs())
        assert event.execution_attempt == 0


# ─── Run 生命周期事件 ──────────────────────────────────────


class TestRunLifecycleEvents:
    def test_run_created(self) -> None:
        event = RunCreated(**_base_kwargs(), agent_id="agent-1", metadata={"k": "v"})
        assert event.event_type == EventType.RUN_CREATED
        assert event.agent_id == "agent-1"
        assert event.metadata == {"k": "v"}

    def test_run_started(self) -> None:
        event = RunStarted(**_base_kwargs(), max_steps=20)
        assert event.event_type == EventType.RUN_STARTED
        assert event.max_steps == 20

    def test_run_state_changed(self) -> None:
        event = RunStateChanged(**_base_kwargs(), old_status="created", new_status="running")
        assert event.event_type == EventType.RUN_STATE_CHANGED
        assert event.old_status == "created"
        assert event.new_status == "running"

    def test_run_completed(self) -> None:
        usage = Usage(input_tokens=100, output_tokens=50)
        event = RunCompleted(**_base_kwargs(), output="hello", usage=usage)
        assert event.event_type == EventType.RUN_COMPLETED
        assert event.output == "hello"
        assert event.usage is not None
        assert event.usage.input_tokens == 100

    def test_run_failed(self) -> None:
        event = RunFailed(
            **_base_kwargs(),
            error_type="TimeoutError",
            error_message="请求超时",
            is_retryable=True,
        )
        assert event.event_type == EventType.RUN_FAILED
        assert event.is_retryable is True

    def test_run_suspended(self) -> None:
        event = RunSuspended(
            **_base_kwargs(),
            suspension_id="susp-001",
            suspension_type="tool_approval",
            reason="需要审批",
        )
        assert event.event_type == EventType.RUN_SUSPENDED
        assert event.suspension_id == "susp-001"

    def test_run_resumed(self) -> None:
        event = RunResumed(
            **_base_kwargs(), suspension_id="susp-001", idempotency_key="idem-001"
        )
        assert event.event_type == EventType.RUN_RESUMED
        assert event.idempotency_key == "idem-001"

    def test_run_cancellation_requested(self) -> None:
        event = RunCancellationRequested(**_base_kwargs(), reason="用户取消")
        assert event.event_type == EventType.RUN_CANCELLATION_REQUESTED
        assert event.reason == "用户取消"

    def test_run_cancelled(self) -> None:
        event = RunCancelled(**_base_kwargs(), reason="用户取消")
        assert event.event_type == EventType.RUN_CANCELLED

    def test_run_terminated(self) -> None:
        event = RunTerminated(**_base_kwargs(), reason="强制终止")
        assert event.event_type == EventType.RUN_TERMINATED


# ─── 模型事件 ──────────────────────────────────────────────


class TestModelEvents:
    def test_model_request_started(self) -> None:
        event = ModelRequestStarted(**_base_kwargs(), model="gpt-4o", step=1)
        assert event.event_type == EventType.MODEL_REQUEST_STARTED
        assert event.model == "gpt-4o"
        assert event.persisted is True

    def test_model_text_delta_not_persisted(self) -> None:
        event = ModelTextDelta(**_base_kwargs(), delta="hello", content_index=0)
        assert event.event_type == EventType.MODEL_TEXT_DELTA
        assert event.persisted is False

    def test_model_reasoning_delta_not_persisted(self) -> None:
        event = ModelReasoningDelta(**_base_kwargs(), delta="让我想想")
        assert event.event_type == EventType.MODEL_REASONING_DELTA
        assert event.persisted is False

    def test_model_tool_call_delta_not_persisted(self) -> None:
        event = ModelToolCallDelta(
            **_base_kwargs(), tool_call_id="tc-001", arguments_delta='{"file":'
        )
        assert event.event_type == EventType.MODEL_TOOL_CALL_DELTA
        assert event.persisted is False

    def test_model_response_completed(self) -> None:
        usage = Usage(input_tokens=200, output_tokens=80)
        event = ModelResponseCompleted(
            **_base_kwargs(),
            finish_reason="tool_calls",
            tool_calls=[{"id": "tc-001", "name": "read_file"}],
            usage=usage,
        )
        assert event.event_type == EventType.MODEL_RESPONSE_COMPLETED
        assert event.finish_reason == "tool_calls"
        assert event.persisted is True


# ─── 工具事件 ──────────────────────────────────────────────


class TestToolEvents:
    def test_tool_call_proposed(self) -> None:
        event = ToolCallProposed(
            **_base_kwargs(),
            tool_call_id="tc-001",
            tool_name="read_file",
            arguments={"path": "/tmp/test.txt"},
        )
        assert event.event_type == EventType.TOOL_CALL_PROPOSED
        assert event.tool_name == "read_file"

    def test_tool_call_modified(self) -> None:
        event = ToolCallModified(
            **_base_kwargs(),
            tool_call_id="tc-001",
            original_arguments={"path": "/etc/passwd"},
            modified_arguments={"path": "/tmp/safe.txt"},
            modified_by="security_interceptor",
        )
        assert event.event_type == EventType.TOOL_CALL_MODIFIED
        assert event.modified_by == "security_interceptor"

    def test_tool_approval_requested(self) -> None:
        event = ToolApprovalRequested(
            **_base_kwargs(),
            suspension_id="susp-001",
            tool_call_id="tc-001",
            tool_name="execute_command",
            arguments={"cmd": "rm -rf /"},
            reason="高风险命令",
        )
        assert event.event_type == EventType.TOOL_APPROVAL_REQUESTED
        assert event.reason == "高风险命令"

    def test_tool_execution_started(self) -> None:
        event = ToolExecutionStarted(
            **_base_kwargs(),
            tool_call_id="tc-001",
            tool_name="read_file",
            execution_id="exec-001",
        )
        assert event.event_type == EventType.TOOL_EXECUTION_STARTED

    def test_tool_execution_progress_not_persisted(self) -> None:
        event = ToolExecutionProgress(
            **_base_kwargs(),
            tool_call_id="tc-001",
            execution_id="exec-001",
            progress=0.5,
            total=1.0,
            message="下载中",
        )
        assert event.event_type == EventType.TOOL_EXECUTION_PROGRESS
        assert event.persisted is False

    def test_tool_execution_completed(self) -> None:
        event = ToolExecutionCompleted(
            **_base_kwargs(),
            tool_call_id="tc-001",
            tool_name="read_file",
            execution_id="exec-001",
            is_error=False,
            duration_ms=150.5,
        )
        assert event.event_type == EventType.TOOL_EXECUTION_COMPLETED
        assert event.duration_ms == 150.5

    def test_tool_execution_failed(self) -> None:
        event = ToolExecutionFailed(
            **_base_kwargs(),
            tool_call_id="tc-001",
            tool_name="read_file",
            execution_id="exec-001",
            error_type="FileNotFoundError",
            error_message="文件不存在",
        )
        assert event.event_type == EventType.TOOL_EXECUTION_FAILED


# ─── 系统事件 ──────────────────────────────────────────────


class TestSystemEvents:
    def test_checkpoint_created(self) -> None:
        event = CheckpointCreated(**_base_kwargs(), checkpoint_id="cp-001", step=3)
        assert event.event_type == EventType.CHECKPOINT_CREATED
        assert event.step == 3

    def test_usage_updated(self) -> None:
        usage = Usage(input_tokens=500, output_tokens=200, total_tokens=700)
        event = UsageUpdated(**_base_kwargs(), usage=usage)
        assert event.event_type == EventType.USAGE_UPDATED
        assert event.usage is not None
        assert event.usage.total_tokens == 700

    def test_artifact_created(self) -> None:
        event = ArtifactCreated(
            **_base_kwargs(),
            artifact_id="art-001",
            artifact_type="file",
            name="output.py",
            path="/workspace/output.py",
        )
        assert event.event_type == EventType.ARTIFACT_CREATED
        assert event.path == "/workspace/output.py"


# ─── RuntimeEventUnion 覆盖 ───────────────────────────────


class TestRuntimeEventUnion:
    def test_union_covers_all_subtypes(self) -> None:
        """验证 RuntimeEventUnion 联合类型包含所有 25 种事件子类。"""
        expected_types = {
            RunCreated,
            RunStarted,
            RunStateChanged,
            RunCompleted,
            RunFailed,
            RunSuspended,
            RunResumed,
            RunCancellationRequested,
            RunCancelled,
            RunTerminated,
            ModelRequestStarted,
            ModelTextDelta,
            ModelReasoningDelta,
            ModelToolCallDelta,
            ModelResponseCompleted,
            ToolCallProposed,
            ToolCallModified,
            ToolApprovalRequested,
            ToolExecutionStarted,
            ToolExecutionProgress,
            ToolExecutionCompleted,
            ToolExecutionFailed,
            CheckpointCreated,
            UsageUpdated,
            ArtifactCreated,
        }
        # Python 3.10+ UnionType 无法直接取参数，通过 __args__ 获取
        union_args = set(RuntimeEventUnion.__args__)
        assert union_args == expected_types, (
            f"遗漏: {expected_types - union_args}, 多余: {union_args - expected_types}"
        )


# ─── create_event 工厂 ────────────────────────────────────


class TestCreateEvent:
    def test_creates_event_with_auto_fields(self) -> None:
        event = create_event(
            RunCreated, run_id="run-100", session_id="sess-100", sequence=5, agent_id="a1"
        )
        assert isinstance(event, RunCreated)
        assert event.run_id == "run-100"
        assert event.session_id == "sess-100"
        assert event.sequence == 5
        assert event.agent_id == "a1"
        assert event.event_id  # 自动生成
        assert event.timestamp.tzinfo == timezone.utc  # 自动补时区

    def test_creates_different_events(self) -> None:
        e1 = create_event(RunStarted, "r1", "s1", 1)
        e2 = create_event(RunStarted, "r1", "s1", 2)
        assert e1.event_id != e2.event_id
        assert e1.sequence != e2.sequence
