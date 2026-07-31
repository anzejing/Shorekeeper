"""Runtime API 测试。"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.runtime import set_runtime
from app.main import app
from app.runtime.litellm_client import (
    DONE,
    TEXT_DELTA,
    LiteLLMCompletionRequest,
    LiteLLMStreamEvent,
)
from app.runtime.models import Allow, Message, Role, RunStatus
from app.runtime.runtime import NativePythonRuntime
from app.runtime.store import SQLiteCheckpointStore, SQLiteEventStore, SQLiteRunStore, init_db


# ─── Mock 依赖 ────────────────────────────────────────────


class MockEventPublisher:
    def __init__(self, event_store: Any = None) -> None:
        self.events: list[Any] = []
        self._event_store = event_store

    async def publish(self, event: Any) -> None:
        self.events.append(event)
        if self._event_store is not None:
            await self._event_store.save(event)


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
    def __init__(self, event_lists: list[list[LiteLLMStreamEvent]]) -> None:
        self._event_lists = event_lists
        self._call_count = 0

    async def stream_completion(
        self, request: LiteLLMCompletionRequest, *, cancellation: Any
    ) -> AsyncIterator[LiteLLMStreamEvent]:
        events = self._event_lists[self._call_count]
        self._call_count += 1
        for event in events:
            await asyncio.sleep(0)
            yield event


# ─── 辅助 ─────────────────────────────────────────────────


async def _setup_runtime(llm: Any = None) -> NativePythonRuntime:
    """创建并注册 Runtime。"""
    db = await init_db()
    run_store = SQLiteRunStore(db)
    event_store = SQLiteEventStore(db)
    checkpoint_store = SQLiteCheckpointStore(db)
    publisher = MockEventPublisher(event_store=event_store)

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
        event_store=event_store,
        default_model="test-model",
    )
    set_runtime(runtime)
    return runtime


# ─── 测试 ─────────────────────────────────────────────────


class TestCreateRun:
    @pytest.mark.asyncio
    async def test_create_run(self) -> None:
        await _setup_runtime()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/runs",
                json={
                    "session_id": "sess-1",
                    "agent_id": "agent-1",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"]
        assert data["status"] == "created"


class TestExecuteRun:
    @pytest.mark.asyncio
    async def test_execute_run(self) -> None:
        llm = FakeLiteLLMClient(
            [[LiteLLMStreamEvent(type=TEXT_DELTA, content="世界"), LiteLLMStreamEvent(type=DONE, finish_reason="stop")]]
        )
        await _setup_runtime(llm)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 创建
            create_resp = await client.post(
                "/api/runs",
                json={
                    "session_id": "sess-1",
                    "agent_id": "agent-1",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
            run_id = create_resp.json()["run_id"]

            # 执行
            exec_resp = await client.post(f"/api/runs/{run_id}/execute")
            assert exec_resp.status_code == 200

            # 等待完成
            await asyncio.sleep(0.3)

            # 查询状态
            get_resp = await client.get(f"/api/runs/{run_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_not_found(self) -> None:
        await _setup_runtime()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/runs/nonexistent/execute")
            assert resp.status_code == 404


class TestGetRun:
    @pytest.mark.asyncio
    async def test_get_run(self) -> None:
        await _setup_runtime()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_resp = await client.post(
                "/api/runs",
                json={
                    "session_id": "sess-1",
                    "agent_id": "agent-1",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
            run_id = create_resp.json()["run_id"]

            get_resp = await client.get(f"/api/runs/{run_id}")
            assert get_resp.status_code == 200
            data = get_resp.json()
            assert data["run_id"] == run_id
            assert data["session_id"] == "sess-1"
            assert data["status"] == "created"

    @pytest.mark.asyncio
    async def test_get_run_not_found(self) -> None:
        await _setup_runtime()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/runs/nonexistent")
            assert resp.status_code == 404


class TestCancelRun:
    @pytest.mark.asyncio
    async def test_cancel_run(self) -> None:
        await _setup_runtime()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_resp = await client.post(
                "/api/runs",
                json={
                    "session_id": "sess-1",
                    "agent_id": "agent-1",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
            run_id = create_resp.json()["run_id"]

            cancel_resp = await client.post(
                f"/api/runs/{run_id}/cancel",
                json={"reason": "用户取消"},
            )
            assert cancel_resp.status_code == 200


class TestStreamRun:
    @pytest.mark.asyncio
    async def test_stream_returns_sse(self) -> None:
        llm = FakeLiteLLMClient(
            [[LiteLLMStreamEvent(type=TEXT_DELTA, content="你好"), LiteLLMStreamEvent(type=DONE, finish_reason="stop")]]
        )
        await _setup_runtime(llm)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_resp = await client.post(
                "/api/runs",
                json={
                    "session_id": "sess-1",
                    "agent_id": "agent-1",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
            run_id = create_resp.json()["run_id"]

            # 启动执行
            await client.post(f"/api/runs/{run_id}/execute")

            # 等待完成
            await asyncio.sleep(0.3)

            # 获取事件流
            stream_resp = await client.get(
                f"/api/runs/{run_id}/stream",
                headers={"Accept": "text/event-stream"},
            )
            assert stream_resp.status_code == 200
            assert "text/event-stream" in stream_resp.headers["content-type"]

            # 验证 SSE 格式
            content = stream_resp.text
            assert "event:" in content
            assert "data:" in content

    @pytest.mark.asyncio
    async def test_stream_not_found(self) -> None:
        await _setup_runtime()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/runs/nonexistent/stream")
            assert resp.status_code == 404


class TestResumeRun:
    @pytest.mark.asyncio
    async def test_resume_not_found(self) -> None:
        await _setup_runtime()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/runs/nonexistent/resume",
                json={
                    "approved": True,
                    "idempotency_key": "key-1",
                },
            )
            assert resp.status_code == 404


class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
