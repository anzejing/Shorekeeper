"""热切换集成测试：Run 挂起（审批）期间切换全局模型，resume 仍使用原模型。

验证 Runtime 从 RunSnapshot.metadata 恢复 model/llm_extra 的能力。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from app.runtime.litellm_client import (
    DONE,
    TEXT_DELTA,
    TOOL_CALL_DELTA,
    LiteLLMCompletionRequest,
    LiteLLMStreamEvent,
)
from app.runtime.models import (
    Allow,
    Message,
    Role,
    RunRequest,
    RunStatus,
    SuspendDecision,
    SuspendRequest,
    SuspensionType,
    ToolCall,
)
from app.runtime.runtime import NativePythonRuntime
from app.runtime.store import SQLiteCheckpointStore, SQLiteEventStore, SQLiteRunStore, init_db


# ─── Mock ─────────────────────────────────────────────────


class MockEventPublisher:
    async def publish(self, event) -> None:
        pass


class SuspendInterceptor:
    """首次工具调用挂起，之后允许。"""

    def __init__(self) -> None:
        self._suspended = False

    async def process(self, tool_call: ToolCall) -> Any:
        if not self._suspended:
            self._suspended = True
            return SuspendDecision(
                request=SuspendRequest(
                    SuspensionType.TOOL_APPROVAL, tool_call, "需要审批"
                )
            )
        return Allow()


class RecordingLLM:
    """记录每次调用的模型名，第二次返回文本。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def stream_completion(
        self, request: LiteLLMCompletionRequest, *, cancellation: Any
    ) -> AsyncIterator[LiteLLMStreamEvent]:
        self.calls.append(request.model)
        if len(self.calls) == 1:
            # 第一次：请求工具调用 → 触发挂起
            yield LiteLLMStreamEvent(
                type=TOOL_CALL_DELTA,
                tool_call_id="tc-1",
                tool_name="bash_execute",
                arguments_delta='{"cmd": "ls"}',
            )
            yield LiteLLMStreamEvent(type=DONE, finish_reason="tool_calls")
        else:
            # 第二次（resume 后）：返回文本
            yield LiteLLMStreamEvent(type=TEXT_DELTA, content="完成")
            yield LiteLLMStreamEvent(type=DONE, finish_reason="stop")


class MockToolExecutor:
    async def execute(self, tool_call: ToolCall, *, cancellation: Any) -> Any:
        from app.runtime.models import TextPart, ToolResult

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text="ok")],
        )


# ─── 测试 ─────────────────────────────────────────────────


class TestHotSwitch:
    @pytest.mark.asyncio
    async def test_resume_uses_run_original_model(self) -> None:
        """挂起期间全局切模型，resume 仍用 Run 创建时的模型。"""
        db = await init_db()
        llm = RecordingLLM()
        runtime = NativePythonRuntime(
            llm=llm,
            tool_executor=MockToolExecutor(),
            interceptor=SuspendInterceptor(),
            publisher=MockEventPublisher(),
            run_store=SQLiteRunStore(db),
            checkpoint_store=SQLiteCheckpointStore(db),
            event_store=SQLiteEventStore(db),
            default_model="default-model",  # 初始全局默认
        )

        # 用 Run 指定模型（等价于聊天请求携带 model）
        request = RunRequest(
            session_id="sess-1",
            agent_id="chat",
            messages=[Message(role=Role.USER, content="hello")],
            max_steps=5,
            metadata={
                "model": "openai/model-a",
                "llm_extra": {"api_key": "key-a", "base_url": "https://a.local/v1"},
                "model_ref": {"provider_id": "p1", "model_id": "model-a"},
            },
        )
        handle = await runtime.create_run(request)
        await runtime.execute(handle.run_id)

        # 等待第一次 LLM 调用发生（agent loop 异步执行）
        for _ in range(100):
            if llm.calls:
                break
            await asyncio.sleep(0.02)

        # 第一次调用用 Run 指定模型
        assert llm.calls == ["openai/model-a"]

        # Run 挂起（审批中）
        snapshot = await runtime.get_run(handle.run_id)
        assert snapshot.status == RunStatus.WAITING

        # 模拟全局切到另一个模型（runtime 默认模型变化）
        runtime._default_model = "openai/model-b"
        runtime._llm_extra = {"api_key": "key-b", "base_url": "https://b.local/v1"}

        # 恢复 Run
        from app.runtime.models import ResumeInput

        await runtime.resume(
            handle.run_id,
            ResumeInput(approved=True, idempotency_key="resume-1"),
        )

        # 等待完成
        snapshot = await runtime.wait_until_terminal(handle.run_id, timeout=10.0)
        assert snapshot.status == RunStatus.COMPLETED

        # 第二次调用（resume 后）仍用 Run 原模型，未串模型
        assert llm.calls == ["openai/model-a", "openai/model-a"]

    @pytest.mark.asyncio
    async def test_run_without_metadata_uses_global_default(self) -> None:
        """Run 不带模型元数据 → 用全局默认（兼容旧调用）。"""
        db = await init_db()
        llm = RecordingLLM()

        class AllowAllInterceptor:
            async def process(self, tool_call: ToolCall) -> Any:
                return Allow()

        runtime = NativePythonRuntime(
            llm=llm,
            tool_executor=MockToolExecutor(),
            interceptor=AllowAllInterceptor(),
            publisher=MockEventPublisher(),
            run_store=SQLiteRunStore(db),
            checkpoint_store=SQLiteCheckpointStore(db),
            event_store=SQLiteEventStore(db),
            default_model="openai/global-default",
        )
        request = RunRequest(
            session_id="sess-2",
            agent_id="chat",
            messages=[Message(role=Role.USER, content="hi")],
            metadata={},
        )
        handle = await runtime.create_run(request)
        await runtime.execute(handle.run_id)
        snapshot = await runtime.wait_until_terminal(handle.run_id, timeout=10.0)
        assert snapshot.status == RunStatus.COMPLETED
        # 工具调用轮 + 最终回复轮均用全局默认模型
        assert llm.calls == ["openai/global-default", "openai/global-default"]
