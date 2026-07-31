"""NativePythonRuntime 测试。

Mock LiteLLMClient，测试 Run 生命周期。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from app.runtime.events import (
    RunCancelled,
    RunCancellationRequested,
    RunCompleted,
    RunCreated,
    RunFailed,
    RunStateChanged,
)
from app.runtime.litellm_client import (
    DONE,
    TEXT_DELTA,
    LiteLLMCompletionRequest,
    LiteLLMStreamEvent,
)
from app.runtime.models import (
    Allow,
    Checkpoint,
    Message,
    PendingWrite,
    Role,
    RunHandle,
    RunId,
    RunRequest,
    RunSnapshot,
    RunStatus,
    Usage,
)
from app.runtime.runtime import NativePythonRuntime, RunNotFoundError
from app.runtime.store import SQLiteCheckpointStore, SQLiteEventStore, SQLiteRunStore, init_db


# ─── Mock 依赖 ────────────────────────────────────────────


class MockEventPublisher:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)

    def get_events_by_type(self, event_type: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, event_type)]


class MockToolExecutor:
    async def execute(self, tool_call: Any, *, cancellation: Any, context: Any = None) -> Any:
        from app.runtime.models import TextPart, ToolResult

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text="ok")],
        )


class MockInterceptorChain:
    async def process(self, tool_call: Any) -> Any:
        return Allow()


class FakeLiteLLMClient:
    """返回预设的流式事件。"""

    def __init__(self, event_lists: list[list[LiteLLMStreamEvent]]) -> None:
        self._event_lists = event_lists
        self._call_count = 0

    async def stream_completion(
        self, request: LiteLLMCompletionRequest, *, cancellation: Any
    ) -> AsyncIterator[LiteLLMStreamEvent]:
        events = self._event_lists[self._call_count]
        self._call_count += 1
        for event in events:
            await asyncio.sleep(0)  # 让出控制权
            yield event


# ─── 辅助 ─────────────────────────────────────────────────


async def _create_runtime(llm: Any = None) -> tuple[NativePythonRuntime, MockEventPublisher]:
    """创建 Runtime 实例。"""
    db = await init_db()
    run_store = SQLiteRunStore(db)
    event_store = SQLiteEventStore(db)
    checkpoint_store = SQLiteCheckpointStore(db)
    publisher = MockEventPublisher()

    if llm is None:
        llm = FakeLiteLLMClient(
            [[LiteLLMStreamEvent(type=TEXT_DELTA, content="你好"), LiteLLMStreamEvent(type=DONE, finish_reason="stop")]]
        )

    runtime = NativePythonRuntime(
        llm=llm,
        tool_executor=MockToolExecutor(),
        interceptor=MockInterceptorChain(),
        publisher=publisher,
        run_store=run_store,
        checkpoint_store=checkpoint_store,
        default_model="test-model",
    )
    return runtime, publisher


def _make_request(
    messages: list[Message] | None = None,
    max_steps: int = 10,
) -> RunRequest:
    """构造 RunRequest。"""
    return RunRequest(
        session_id="sess-1",
        agent_id="agent-1",
        messages=messages or [Message(role=Role.USER, content="hello")],
        max_steps=max_steps,
    )


# ─── 测试 ─────────────────────────────────────────────────


class TestCreateRun:
    @pytest.mark.asyncio
    async def test_create_run_returns_handle(self) -> None:
        runtime, publisher = await _create_runtime()
        handle = await runtime.create_run(_make_request())

        assert isinstance(handle, RunHandle)
        assert handle.run_id
        assert handle.status == RunStatus.CREATED

        # 验证 RunCreated 事件
        created = publisher.get_events_by_type(RunCreated)
        assert len(created) == 1

    @pytest.mark.asyncio
    async def test_create_run_persists_snapshot(self) -> None:
        runtime, _ = await _create_runtime()
        handle = await runtime.create_run(_make_request())

        snapshot = await runtime.get_run(RunId(handle.run_id))
        assert snapshot.status == RunStatus.CREATED
        assert snapshot.session_id == "sess-1"
        assert snapshot.agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_create_run_not_found(self) -> None:
        runtime, _ = await _create_runtime()
        with pytest.raises(RunNotFoundError):
            await runtime.get_run(RunId("nonexistent"))


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_completes(self) -> None:
        llm = FakeLiteLLMClient(
            [[LiteLLMStreamEvent(type=TEXT_DELTA, content="世界"), LiteLLMStreamEvent(type=DONE, finish_reason="stop")]]
        )
        runtime, publisher = await _create_runtime(llm)

        handle = await runtime.create_run(_make_request())
        await runtime.execute(RunId(handle.run_id))

        # 等待 Agent Loop 完成
        await asyncio.sleep(0.2)

        # 验证最终状态
        snapshot = await runtime.get_run(RunId(handle.run_id))
        assert snapshot.status == RunStatus.COMPLETED

        # 验证事件
        assert len(publisher.get_events_by_type(RunCreated)) == 1
        assert len(publisher.get_events_by_type(RunStateChanged)) >= 1
        assert len(publisher.get_events_by_type(RunCompleted)) == 1

    @pytest.mark.asyncio
    async def test_execute_already_running_ignored(self) -> None:
        llm = FakeLiteLLMClient(
            [[LiteLLMStreamEvent(type=TEXT_DELTA, content="ok"), LiteLLMStreamEvent(type=DONE, finish_reason="stop")]]
        )
        runtime, _ = await _create_runtime(llm)

        handle = await runtime.create_run(_make_request())
        await runtime.execute(RunId(handle.run_id))
        # 第二次调用应被忽略
        await runtime.execute(RunId(handle.run_id))

        await asyncio.sleep(0.2)

        snapshot = await runtime.get_run(RunId(handle.run_id))
        assert snapshot.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_litellm_error(self) -> None:
        """LiteLLM 错误导致 RunFailed。"""
        from app.runtime.litellm_client import LiteLLMError

        class ErrorLiteLLMClient:
            async def stream_completion(self, request: Any, *, cancellation: Any) -> AsyncIterator[LiteLLMStreamEvent]:
                raise LiteLLMError("API 错误")
                yield  # type: ignore[misc]

        runtime, publisher = await _create_runtime(ErrorLiteLLMClient())

        handle = await runtime.create_run(_make_request())
        await runtime.execute(RunId(handle.run_id))

        await asyncio.sleep(0.2)

        snapshot = await runtime.get_run(RunId(handle.run_id))
        assert snapshot.status == RunStatus.FAILED

        failed = publisher.get_events_by_type(RunFailed)
        assert len(failed) == 1


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel(self) -> None:
        """取消正在运行的 Run。"""

        class SlowLiteLLMClient:
            async def stream_completion(self, request: Any, *, cancellation: Any) -> AsyncIterator[LiteLLMStreamEvent]:
                # 模拟慢响应，检查取消
                for i in range(100):
                    if cancellation.is_cancelled:
                        return
                    await asyncio.sleep(0.01)
                yield LiteLLMStreamEvent(type=DONE, finish_reason="stop")

        runtime, publisher = await _create_runtime(SlowLiteLLMClient())

        handle = await runtime.create_run(_make_request())
        await runtime.execute(RunId(handle.run_id))

        # 短暂等待后取消
        await asyncio.sleep(0.1)
        await runtime.cancel(RunId(handle.run_id), reason="用户取消")

        snapshot = await runtime.get_run(RunId(handle.run_id))
        assert snapshot.status == RunStatus.CANCELLED

        cancel_events = publisher.get_events_by_type(RunCancellationRequested)
        assert len(cancel_events) == 1

    @pytest.mark.asyncio
    async def test_cancel_terminal_ignored(self) -> None:
        """取消终态 Run 被忽略。"""
        llm = FakeLiteLLMClient(
            [[LiteLLMStreamEvent(type=TEXT_DELTA, content="ok"), LiteLLMStreamEvent(type=DONE, finish_reason="stop")]]
        )
        runtime, _ = await _create_runtime(llm)

        handle = await runtime.create_run(_make_request())
        await runtime.execute(RunId(handle.run_id))
        await asyncio.sleep(0.2)

        # 已完成，取消应被忽略
        await runtime.cancel(RunId(handle.run_id))
        snapshot = await runtime.get_run(RunId(handle.run_id))
        assert snapshot.status == RunStatus.COMPLETED


class TestGetRun:
    @pytest.mark.asyncio
    async def test_get_run(self) -> None:
        runtime, _ = await _create_runtime()
        handle = await runtime.create_run(_make_request())

        snapshot = await runtime.get_run(RunId(handle.run_id))
        assert snapshot.run_id == handle.run_id
        assert snapshot.session_id == "sess-1"
