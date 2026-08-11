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
from app.memory.tools import MEMORY_TOOLS
from app.models_config.service import ModelConfigService
from app.models_config.store import ModelConfigStore, init_models_config_db
from app.plugin.loader import PluginLoader
from app.runtime.litellm_client import DONE, TEXT_DELTA, LiteLLMCompletionRequest, LiteLLMStreamEvent
from app.runtime.models import Allow, Message, Role
from app.runtime.runtime import NativePythonRuntime
from app.runtime.store import SQLiteCheckpointStore, SQLiteEventStore, SQLiteRunStore, init_db
from app.skill.loader import SkillLoader
from app.skill.service import SkillService
from app.skill.store import SQLiteSkillStore, init_skill_db
from app.tool.definitions import PROXY_TOOLS
from app.tool.registry import ToolRegistry
from app.tools import BUILTIN_TOOLS


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
    plugin_loader = PluginLoader(tmp_path / "plugins", skill_loader, skill_store)
    skill_service = SkillService(skill_store, skill_loader, plugin_loader)
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

    # 模型配置模块（测试用：创建 provider + 模型 + 设为当前）
    await init_models_config_db(db)
    models_store = ModelConfigStore(db)
    models_service = ModelConfigService(models_store, tmp_path)
    await models_service.create_provider(
        {
            "provider_id": "test-provider",
            "name": "Test Provider",
            "kind": "openai_like",
            "base_url": "https://test.local/v1",
            "api_key": "test-key",
        }
    )
    await models_service.add_model("test-provider", "test-model")
    await models_service.set_current("test-provider", "test-model")

    # 注册 API
    from app.api.runtime import set_runtime
    set_runtime(runtime)
    fixed_tools = [*BUILTIN_TOOLS, *MEMORY_TOOLS, *PROXY_TOOLS]
    init_chat_api(memory_service, skill_service, fixed_tools, models_service)

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

    @pytest.mark.asyncio
    async def test_chat_without_current_model_returns_400(self, tmp_path: Path) -> None:
        """未配置当前模型时发送消息 → 400 提示。"""
        db = await init_db()
        await init_memory_db(db)
        await init_models_config_db(db)
        await init_skill_db(db)

        # 只初始化模型配置模块，不设置当前模型
        models_service = ModelConfigService(ModelConfigStore(db), tmp_path)

        from app.api.chat import init_chat_api as _init
        from app.api.runtime import set_runtime
        from app.runtime.litellm_client import DONE as _DONE
        from app.runtime.litellm_client import TEXT_DELTA as _TEXT_DELTA
        from app.runtime.litellm_client import LiteLLMCompletionRequest as _LCR
        from app.runtime.litellm_client import LiteLLMStreamEvent as _LSE

        class _FakeLLM:
            async def stream_completion(self, request: _LCR, *, cancellation):
                yield _LSE(type=_TEXT_DELTA, content="hi")
                yield _LSE(type=_DONE, finish_reason="stop")

        run_store = SQLiteRunStore(db)
        runtime = NativePythonRuntime(
            llm=_FakeLLM(),
            tool_executor=ToolRegistry(),
            interceptor=MockInterceptorChain(),
            publisher=MockEventPublisher(),
            run_store=run_store,
            checkpoint_store=SQLiteCheckpointStore(db),
            event_store=SQLiteEventStore(db),
            default_model="",
        )
        set_runtime(runtime)
        _init(
            MemoryService(
                SQLiteSessionStore(db), SQLiteMemoryStore(db)
            ),
            SkillService(
                SQLiteSkillStore(db),
                SkillLoader(tmp_path / "skills", SQLiteSkillStore(db)),
                PluginLoader(
                    tmp_path / "plugins",
                    SkillLoader(tmp_path / "skills", SQLiteSkillStore(db)),
                    SQLiteSkillStore(db),
                ),
            ),
            [*BUILTIN_TOOLS, *MEMORY_TOOLS, *PROXY_TOOLS],
            models_service,
        )

        test_app = FastAPI()
        test_app.include_router(chat_router)
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "你好"},
            )
        assert resp.status_code == 400
        assert "模型" in resp.json()["detail"]
