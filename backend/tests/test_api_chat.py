"""Chat API 测试（使用 Mock LLM）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.chat import init_chat_api, router as chat_router
from app.memory.service import MemoryService
from app.memory.sqlite_store import SQLiteMemoryStore, SQLiteSessionStore, init_memory_db
from app.runtime.litellm_client import DONE, TEXT_DELTA, LiteLLMCompletionRequest, LiteLLMStreamEvent
from app.runtime.models import Allow, Message, Role
from app.runtime.runtime import NativePythonRuntime
from app.runtime.store import SQLiteCheckpointStore, SQLiteEventStore, SQLiteRunStore, init_db
from app.skill.loader import SkillLoader
from app.skill.service import SkillService
from app.skill.store import SQLiteSkillStore, init_skill_db
from app.tool.registry import ToolRegistry


# ─── Mock ─────────────────────────────────────────────────


class MockEventPublisher:
    async def publish(self, event):
        pass


class MockInterceptorChain:
    async def process(self, tool_call):
        return Allow()


class FakeLiteLLMClient:
    def __init__(self, reply: str = "你好！有什么可以帮助你的？") -> None:
        self._reply = reply

    async def stream_completion(
        self, request: LiteLLMCompletionRequest, *, cancellation
    ) -> AsyncIterator[LiteLLMStreamEvent]:
        yield LiteLLMStreamEvent(type=TEXT_DELTA, content=self._reply)
        await asyncio.sleep(0)
        yield LiteLLMStreamEvent(type=DONE, finish_reason="stop")


# ─── 辅助 ─────────────────────────────────────────────────


async def _setup(
    tmp_path: Path,
    llm_reply: str = "你好！有什么可以帮助你的？",
) -> FastAPI:
    """创建测试专用 app。"""
    db = await init_db()
    await init_memory_db(db)
    await init_skill_db(db)

    # Memory
    session_store = SQLiteSessionStore(db)
    memory_store = SQLiteMemoryStore(db)
    memory_service = MemoryService(session_store, memory_store)

    # Skill
    skill_store = SQLiteSkillStore(db)
    skill_loader = SkillLoader(tmp_path / "skills", skill_store)
    skill_service = SkillService(skill_store, skill_loader)
    await skill_service.initialize()

    # ToolRegistry
    tool_registry = ToolRegistry()

    # Runtime
    run_store = SQLiteRunStore(db)
    event_store = SQLiteEventStore(db)
    checkpoint_store = SQLiteCheckpointStore(db)

    runtime = NativePythonRuntime(
        llm=FakeLiteLLMClient(llm_reply),
        tool_executor=tool_registry,
        interceptor=MockInterceptorChain(),
        publisher=MockEventPublisher(),
        run_store=run_store,
        checkpoint_store=checkpoint_store,
        event_store=event_store,
        default_model="test-model",
    )

    # 注册 API
    from app.api.runtime import set_runtime
    set_runtime(runtime)
    init_chat_api(memory_service, skill_service, tool_registry)

    test_app = FastAPI()
    test_app.include_router(chat_router)
    return test_app


# ─── 测试 ─────────────────────────────────────────────────


class TestChat:
    @pytest.mark.asyncio
    async def test_basic_chat(self, tmp_path: Path) -> None:
        app = await _setup(tmp_path, llm_reply="你好！")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "你好"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == "你好！"
        assert data["session_id"]
        assert data["run_id"]

    @pytest.mark.asyncio
    async def test_chat_creates_session(self, tmp_path: Path) -> None:
        app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 第一次调用，不传 session_id
            resp1 = await client.post(
                "/api/chat",
                json={"message": "第一条消息"},
            )
            session_id = resp1.json()["session_id"]

            # 第二次调用，传 session_id
            resp2 = await client.post(
                "/api/chat",
                json={"message": "第二条消息", "session_id": session_id},
            )

        assert resp2.status_code == 200
        assert resp2.json()["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_chat_session_not_found(self, tmp_path: Path) -> None:
        app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "你好", "session_id": "nonexistent"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_chat_returns_reply(self, tmp_path: Path) -> None:
        app = await _setup(tmp_path, llm_reply="收到你的消息了")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "测试消息"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == "收到你的消息了"
        assert data["session_id"]
        assert data["run_id"]

    @pytest.mark.asyncio
    async def test_chat_multi_turn(self, tmp_path: Path) -> None:
        app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 第一轮
            resp1 = await client.post(
                "/api/chat",
                json={"message": "你好"},
            )
            session_id = resp1.json()["session_id"]

            # 第二轮（同一 session）
            resp2 = await client.post(
                "/api/chat",
                json={"message": "再见", "session_id": session_id},
            )

        assert resp2.status_code == 200
        assert resp2.json()["session_id"] == session_id
