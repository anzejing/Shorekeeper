"""Tests for runtime domain models."""

from __future__ import annotations

from datetime import datetime, timezone

from app.runtime.models import (
    Allow,
    Checkpoint,
    CancellationCapability,
    EventDeliveryGuarantee,
    Message,
    Modify,
    PendingWrite,
    Reject,
    Replace,
    ResumeInput,
    Role,
    RunHandle,
    RunRequest,
    RunSnapshot,
    RunStatus,
    SuspendDecision,
    SuspendRequest,
    Suspension,
    SuspensionCapability,
    SuspensionId,
    SuspensionType,
    SideEffectLevel,
    TextPart,
    ToolCall,
    ToolCallPart,
    ToolDecision,
    ToolDef,
    ToolExecution,
    ToolExecutionId,
    ToolResult,
    ToolResultPart,
    Usage,
    RuntimeCapabilities,
    RunId,
    SessionId,
    new_event_id,
    new_run_id,
    new_suspension_id,
    new_tool_execution_id,
)


# ─── Identifier generation ─────────────────────────────────


def test_new_run_id_is_unique():
    ids = {new_run_id() for _ in range(100)}
    assert len(ids) == 100


def test_new_event_id_is_unique():
    ids = {new_event_id() for _ in range(100)}
    assert len(ids) == 100


def test_new_suspension_id_is_unique():
    ids = {new_suspension_id() for _ in range(100)}
    assert len(ids) == 100


def test_new_tool_execution_id_is_unique():
    ids = {new_tool_execution_id() for _ in range(100)}
    assert len(ids) == 100


# ─── Enums ─────────────────────────────────────────────────


def test_run_status_values():
    assert RunStatus.CREATED.value == "created"
    assert RunStatus.COMPLETED.value == "completed"
    assert RunStatus.CANCELLED.value == "cancelled"
    assert len(RunStatus) == 10


def test_suspension_type_values():
    assert SuspensionType.TOOL_APPROVAL.value == "tool_approval"
    assert len(SuspensionType) == 5


def test_side_effect_level_values():
    assert SideEffectLevel.READ_ONLY.value == "read_only"
    assert SideEffectLevel.IRREVERSIBLE.value == "irreversible"
    assert len(SideEffectLevel) == 4


def test_role_values():
    assert Role.USER.value == "user"
    assert Role.ASSISTANT.value == "assistant"
    assert len(Role) == 4


# ─── Message ───────────────────────────────────────────────


def test_message_with_string_content():
    msg = Message(role=Role.USER, content="hello")
    assert msg.role == Role.USER
    assert msg.content == "hello"
    assert msg.timestamp.tzinfo is not None


def test_message_with_parts():
    parts = [TextPart(text="hello"), TextPart(text="world")]
    msg = Message(role=Role.ASSISTANT, content=parts)
    assert len(msg.content) == 2  # type: ignore[arg-type]


# ─── ToolCall / ToolResult ─────────────────────────────────


def test_tool_call_creation():
    tc = ToolCall(tool_call_id="c1", tool_name="read_file", arguments={"path": "/tmp"})
    assert tc.tool_call_id == "c1"
    assert tc.arguments == {"path": "/tmp"}


def test_tool_result_success():
    tr = ToolResult(tool_call_id="c1", tool_name="read_file", content=[TextPart(text="ok")])
    assert tr.is_error is False


def test_tool_result_error():
    tr = ToolResult(
        tool_call_id="c1", tool_name="read_file", content=[TextPart(text="not found")], is_error=True
    )
    assert tr.is_error is True


# ─── ToolDecision variants ─────────────────────────────────


def test_allow_decision():
    d = Allow()
    assert d.type == "allow"


def test_modify_decision():
    d = Modify(arguments={"key": "new_value"})
    assert d.type == "modify"
    assert d.arguments == {"key": "new_value"}


def test_reject_decision():
    d = Reject(reason="too dangerous")
    assert d.type == "reject"


def test_replace_decision():
    result = ToolResult(tool_call_id="c1", tool_name="t", content=[TextPart(text="replaced")])
    d = Replace(result=result)
    assert d.type == "replace"


def test_suspend_decision():
    req = SuspendRequest(
        suspension_type=SuspensionType.TOOL_APPROVAL,
        tool_call=ToolCall(tool_call_id="c1", tool_name="delete_file", arguments={}),
        reason="needs approval",
    )
    d = SuspendDecision(request=req)
    assert d.type == "suspend"


# ─── Usage ─────────────────────────────────────────────────


def test_usage_add():
    u1 = Usage(input_tokens=100, output_tokens=50, requests=1, cost=0.01)
    u2 = Usage(input_tokens=200, output_tokens=100, requests=2, cost=0.02)
    u1.add(u2)
    assert u1.input_tokens == 300
    assert u1.output_tokens == 150
    assert u1.requests == 3
    assert u1.cost == 0.03


def test_usage_defaults():
    u = Usage()
    assert u.input_tokens == 0
    assert u.cost == 0.0


# ─── RunRequest (Pydantic) ────────────────────────────────


def test_run_request_defaults():
    req = RunRequest(session_id=SessionId("s1"), agent_id="a1")
    assert req.messages == []
    assert req.tools == []
    assert req.max_steps == 20


# ─── RuntimeCapabilities ───────────────────────────────────


def test_default_capabilities():
    cap = RuntimeCapabilities()
    assert cap.streaming is True
    assert cap.parallel_tool_calls is True
    assert cap.blocking_interceptors is True
    assert cap.suspension == SuspensionCapability.IN_PROCESS
    assert cap.cancellation == CancellationCapability.COOPERATIVE


# ─── Checkpoint ────────────────────────────────────────────


def test_checkpoint_creation():
    now = datetime.now(timezone.utc)
    snapshot = RunSnapshot(
        run_id=RunId("r1"),
        session_id=SessionId("s1"),
        agent_id="a1",
        status=RunStatus.RUNNING,
        version=1,
        messages=[],
        current_step=0,
        max_steps=20,
        usage=Usage(),
        suspension_id=None,
        execution_attempt=0,
        created_at=now,
        updated_at=now,
        completed_at=None,
        metadata={},
    )
    cp = Checkpoint(
        id="cp1",
        run_id=RunId("r1"),
        step=0,
        state=snapshot,
        pending_writes=[],
        timestamp=now,
    )
    assert cp.step == 0
    assert cp.schema_version == 1
