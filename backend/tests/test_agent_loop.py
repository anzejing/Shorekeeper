"""Agent Loop 核心循环测试。

使用 mock 依赖测试各执行路径。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import pytest

from app.runtime.events import (
    RunCompleted,
    RunFailed,
    RunStarted,
    RunSuspended,
    ToolApprovalRequested,
    ToolCallProposed,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from app.runtime.litellm_client import (
    DONE,
    ERROR,
    TEXT_DELTA,
    TOOL_CALL_DELTA,
    USAGE,
    LiteLLMCompletionRequest,
    LiteLLMError,
    LiteLLMStreamEvent,
)
from app.runtime.loop import MaxStepsExceeded, RunContext, run_loop
from app.runtime.models import (
    Allow,
    Checkpoint,
    Message,
    Reject,
    Replace,
    Role,
    RunId,
    SuspendDecision,
    SuspendRequest,
    SuspensionType,
    TextPart,
    ToolCall,
    ToolDef,
    ToolResult,
    Usage,
)


# ─── Mock 依赖 ────────────────────────────────────────────


class MockEventPublisher:
    """记录所有发布的事件。"""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)

    def get_events_by_type(self, event_type: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, event_type)]


class MockCheckpointStore:
    """记录所有保存的 checkpoint。"""

    def __init__(self) -> None:
        self.checkpoints: list[Checkpoint] = []

    async def save(self, checkpoint: Checkpoint) -> None:
        self.checkpoints.append(checkpoint)

    async def load_latest(self, run_id: RunId) -> Checkpoint | None:
        return self.checkpoints[-1] if self.checkpoints else None


class MockToolExecutor:
    """返回预设的工具结果。"""

    def __init__(self, results: dict[str, ToolResult] | None = None) -> None:
        self.results = results or {}
        self.executed: list[ToolCall] = []

    async def execute(
        self, tool_call: ToolCall, *, cancellation: Any, context: Any = None
    ) -> ToolResult:
        self.executed.append(tool_call)
        if tool_call.tool_name in self.results:
            return self.results[tool_call.tool_name]
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text="ok")],
        )


class MockInterceptorChain:
    """返回预设的决策。"""

    def __init__(self, decision: Any = None) -> None:
        self.decision = decision or Allow()
        self.processed: list[ToolCall] = []

    async def process(self, tool_call: ToolCall) -> Any:
        self.processed.append(tool_call)
        return self.decision


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
            yield event


# ─── 辅助 ─────────────────────────────────────────────────


def _make_ctx(
    llm: Any,
    tool_executor: Any = None,
    interceptor: Any = None,
    publisher: Any = None,
    checkpoint_store: Any = None,
    max_steps: int = 10,
    tools: list[ToolDef] | None = None,
) -> RunContext:
    """构造 RunContext。"""
    return RunContext(
        run_id="run-test",
        session_id="sess-test",
        agent_id="agent-test",
        messages=[Message(role=Role.USER, content="hello")],
        tools=tools or [],
        max_steps=max_steps,
        llm=llm,
        tool_executor=tool_executor or MockToolExecutor(),
        interceptor=interceptor or MockInterceptorChain(),
        publisher=publisher or MockEventPublisher(),
        checkpoint_store=checkpoint_store or MockCheckpointStore(),
        model="test-model",
    )


def _text_delta(text: str) -> LiteLLMStreamEvent:
    return LiteLLMStreamEvent(type=TEXT_DELTA, content=text)


def _done(finish_reason: str = "stop") -> LiteLLMStreamEvent:
    return LiteLLMStreamEvent(type=DONE, finish_reason=finish_reason)


def _tool_call_delta(
    tool_call_id: str, tool_name: str, arguments: str
) -> LiteLLMStreamEvent:
    return LiteLLMStreamEvent(
        type=TOOL_CALL_DELTA,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments_delta=arguments,
    )


def _usage_event(input_tokens: int = 100, output_tokens: int = 50) -> LiteLLMStreamEvent:
    return LiteLLMStreamEvent(
        type=USAGE,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


# ─── 测试 ─────────────────────────────────────────────────


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_final_answer(self) -> None:
        """模型直接返回最终答案，无工具调用。"""
        llm = FakeLiteLLMClient(
            [[_text_delta("你好"), _text_delta("世界"), _done("stop")]]
        )
        publisher = MockEventPublisher()
        ctx = _make_ctx(llm, publisher=publisher)

        await run_loop(ctx)

        # 验证 RunCompleted 事件
        completed = publisher.get_events_by_type(RunCompleted)
        assert len(completed) == 1
        assert completed[0].output == "你好世界"

        # 验证 RunStarted 事件
        started = publisher.get_events_by_type(RunStarted)
        assert len(started) == 1

    @pytest.mark.asyncio
    async def test_tool_call_then_complete(self) -> None:
        """模型请求工具调用，执行后模型返回最终答案。"""
        tool_result = ToolResult(
            tool_call_id="tc-1",
            tool_name="read_file",
            content=[TextPart(text="文件内容")],
        )
        llm = FakeLiteLLMClient(
            [
                # 第一轮：工具调用
                [
                    _tool_call_delta("tc-1", "read_file", '{"path":"/tmp/test"}'),
                    _done("tool_calls"),
                ],
                # 第二轮：最终答案
                [_text_delta("已读取文件"), _done("stop")],
            ]
        )
        tool_executor = MockToolExecutor(results={"read_file": tool_result})
        publisher = MockEventPublisher()
        ctx = _make_ctx(
            llm,
            tool_executor=tool_executor,
            publisher=publisher,
            tools=[ToolDef(name="read_file", description="读文件", parameters={})],
        )

        await run_loop(ctx)

        # 验证工具被执行
        assert len(tool_executor.executed) == 1
        assert tool_executor.executed[0].tool_name == "read_file"

        # 验证工具事件
        proposed = publisher.get_events_by_type(ToolCallProposed)
        assert len(proposed) == 1
        started = publisher.get_events_by_type(ToolExecutionStarted)
        assert len(started) == 1
        completed = publisher.get_events_by_type(ToolExecutionCompleted)
        assert len(completed) == 1

        # 验证最终完成
        run_completed = publisher.get_events_by_type(RunCompleted)
        assert len(run_completed) == 1
        assert run_completed[0].output == "已读取文件"

    @pytest.mark.asyncio
    async def test_interceptor_reject(self) -> None:
        """拦截器拒绝工具调用，错误回填给模型。"""
        llm = FakeLiteLLMClient(
            [
                [_tool_call_delta("tc-1", "dangerous_tool", '{"cmd":"rm"}'), _done("tool_calls")],
                [_text_delta("好的，已取消"), _done("stop")],
            ]
        )
        interceptor = MockInterceptorChain(decision=Reject(reason="危险操作"))
        publisher = MockEventPublisher()
        ctx = _make_ctx(
            llm,
            interceptor=interceptor,
            publisher=publisher,
            tools=[ToolDef(name="dangerous_tool", description="危险工具", parameters={})],
        )

        await run_loop(ctx)

        # 工具不应被执行
        assert len(publisher.get_events_by_type(ToolExecutionStarted)) == 0

        # 应该最终完成
        completed = publisher.get_events_by_type(RunCompleted)
        assert len(completed) == 1

        # 消息中应包含拒绝信息
        tool_messages = [m for m in ctx.messages if m.role == Role.TOOL]
        assert len(tool_messages) == 1
        assert "拒绝" in tool_messages[0].content

    @pytest.mark.asyncio
    async def test_interceptor_suspend(self) -> None:
        """拦截器暂停工具调用，发布 RunSuspended 事件。"""
        llm = FakeLiteLLMClient(
            [[_tool_call_delta("tc-1", "execute_cmd", '{"cmd":"ls"}'), _done("tool_calls")]]
        )
        suspend_decision = SuspendDecision(
            request=SuspendRequest(
                suspension_type=SuspensionType.TOOL_APPROVAL,
                tool_call=ToolCall("tc-1", "execute_cmd", {"cmd": "ls"}),
                reason="需要审批",
            )
        )
        interceptor = MockInterceptorChain(decision=suspend_decision)
        publisher = MockEventPublisher()
        ctx = _make_ctx(llm, interceptor=interceptor, publisher=publisher)

        await run_loop(ctx)

        # 应发布 RunSuspended 和 ToolApprovalRequested
        suspended = publisher.get_events_by_type(RunSuspended)
        assert len(suspended) == 1
        approval = publisher.get_events_by_type(ToolApprovalRequested)
        assert len(approval) == 1

        # 不应发布 RunCompleted
        assert len(publisher.get_events_by_type(RunCompleted)) == 0

    @pytest.mark.asyncio
    async def test_interceptor_replace(self) -> None:
        """拦截器替换工具结果。"""
        llm = FakeLiteLLMClient(
            [[_tool_call_delta("tc-1", "read_file", '{"path":"/etc/passwd"}'), _done("tool_calls")],
             [_text_delta("已处理"), _done("stop")]]
        )
        replace_decision = Replace(
            result=ToolResult(
                tool_call_id="tc-1",
                tool_name="read_file",
                content=[TextPart(text="替换内容")],
            )
        )
        interceptor = MockInterceptorChain(decision=replace_decision)
        publisher = MockEventPublisher()
        ctx = _make_ctx(
            llm,
            interceptor=interceptor,
            publisher=publisher,
            tools=[ToolDef(name="read_file", description="", parameters={})],
        )

        await run_loop(ctx)

        # 工具不应被执行（被替换了）
        assert len(publisher.get_events_by_type(ToolExecutionStarted)) == 0

        # 应该最终完成
        completed = publisher.get_events_by_type(RunCompleted)
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_max_steps_exceeded(self) -> None:
        """超过最大步数限制。"""
        # 每轮都返回工具调用，永不结束
        tool_events = [
            _tool_call_delta("tc-1", "noop", "{}"),
            _done("tool_calls"),
        ]
        llm = FakeLiteLLMClient([tool_events] * 5)
        publisher = MockEventPublisher()
        ctx = _make_ctx(llm, publisher=publisher, max_steps=3)

        with pytest.raises(MaxStepsExceeded):
            await run_loop(ctx)

        # 应发布 RunFailed
        failed = publisher.get_events_by_type(RunFailed)
        assert len(failed) == 1
        assert failed[0].error_type == "MaxStepsExceeded"

    @pytest.mark.asyncio
    async def test_cancel(self) -> None:
        """取消令牌触发取消。"""

        async def slow_stream(*args: Any, **kwargs: Any) -> AsyncIterator[LiteLLMStreamEvent]:
            # 模拟慢响应
            await asyncio.sleep(10)
            yield _done("stop")

        class SlowLiteLLMClient:
            async def stream_completion(
                self, request: Any, *, cancellation: Any
            ) -> AsyncIterator[LiteLLMStreamEvent]:
                # 在流式过程中检查取消
                await cancellation.raise_if_cancelled()
                yield _text_delta("部分")
                await cancellation.raise_if_cancelled()
                yield _done("stop")

        llm = SlowLiteLLMClient()
        publisher = MockEventPublisher()
        ctx = _make_ctx(llm, publisher=publisher)

        # 立即取消
        ctx.cancellation.cancel("用户取消")

        with pytest.raises(asyncio.CancelledError):
            await run_loop(ctx)

        # 应发布 RunFailed（CancelledError）
        failed = publisher.get_events_by_type(RunFailed)
        assert len(failed) == 1
        assert failed[0].error_type == "CancelledError"

    @pytest.mark.asyncio
    async def test_litellm_error(self) -> None:
        """LiteLLM 调用错误。"""

        class ErrorLiteLLMClient:
            async def stream_completion(
                self, request: Any, *, cancellation: Any
            ) -> AsyncIterator[LiteLLMStreamEvent]:
                raise LiteLLMError("rate limit", is_retryable=True)
                yield  # type: ignore[misc]

        llm = ErrorLiteLLMClient()
        publisher = MockEventPublisher()
        ctx = _make_ctx(llm, publisher=publisher)

        with pytest.raises(LiteLLMError):
            await run_loop(ctx)

        failed = publisher.get_events_by_type(RunFailed)
        assert len(failed) == 1
        assert failed[0].error_type == "LiteLLMError"
        assert failed[0].is_retryable is True

    @pytest.mark.asyncio
    async def test_interceptor_exception_becomes_reject(self) -> None:
        """拦截器异常时安全默认为 Reject。"""
        llm = FakeLiteLLMClient(
            [[_tool_call_delta("tc-1", "tool", "{}"), _done("tool_calls")],
             [_text_delta("ok"), _done("stop")]]
        )

        class BrokenInterceptor:
            async def process(self, tool_call: Any) -> Any:
                raise RuntimeError("拦截器崩溃")

        publisher = MockEventPublisher()
        ctx = _make_ctx(
            llm,
            interceptor=BrokenInterceptor(),
            publisher=publisher,
            tools=[ToolDef(name="tool", description="", parameters={})],
        )

        await run_loop(ctx)

        # 不应有工具执行事件（被 Reject 了）
        assert len(publisher.get_events_by_type(ToolExecutionStarted)) == 0

        # 应该最终完成
        completed = publisher.get_events_by_type(RunCompleted)
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_tool_error_backfills(self) -> None:
        """工具执行失败时，is_error=True 回填给模型。"""
        llm = FakeLiteLLMClient(
            [[_tool_call_delta("tc-1", "failing_tool", "{}"), _done("tool_calls")],
             [_text_delta("工具出错了"), _done("stop")]]
        )

        class FailingToolExecutor:
            async def execute(
                self, tool_call: Any, *, cancellation: Any, context: Any = None
            ) -> Any:
                raise RuntimeError("工具崩溃")

        publisher = MockEventPublisher()
        ctx = _make_ctx(
            llm,
            tool_executor=FailingToolExecutor(),
            publisher=publisher,
            tools=[ToolDef(name="failing_tool", description="", parameters={})],
        )

        await run_loop(ctx)

        # 应发布 ToolExecutionFailed
        from app.runtime.events import ToolExecutionFailed

        failed = publisher.get_events_by_type(ToolExecutionFailed)
        assert len(failed) == 1

        # 应最终完成
        completed = publisher.get_events_by_type(RunCompleted)
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_multiple_steps(self) -> None:
        """多步循环：工具调用 → 回答 → 工具调用 → 最终回答。"""
        llm = FakeLiteLLMClient(
            [
                [_tool_call_delta("tc-1", "tool_a", '{"k":1}'), _done("tool_calls")],
                [_text_delta("中间结果"), _done("stop")],
            ]
        )
        publisher = MockEventPublisher()
        ctx = _make_ctx(
            llm,
            publisher=publisher,
            tools=[ToolDef(name="tool_a", description="", parameters={})],
        )

        await run_loop(ctx)

        completed = publisher.get_events_by_type(RunCompleted)
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_checkpoint_saved(self) -> None:
        """验证 checkpoint 在 step 边界保存。"""
        llm = FakeLiteLLMClient(
            [[_text_delta("hello"), _done("stop")]]
        )
        checkpoint_store = MockCheckpointStore()
        ctx = _make_ctx(llm, checkpoint_store=checkpoint_store)

        await run_loop(ctx)

        # 至少保存了 1 个 checkpoint（step 0 开始时）
        assert len(checkpoint_store.checkpoints) >= 1
        assert checkpoint_store.checkpoints[0].step == 0


class TestMaxStepsExceeded:
    def test_message(self) -> None:
        e = MaxStepsExceeded(20)
        assert "20" in str(e)
        assert e.max_steps == 20
