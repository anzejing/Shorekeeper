"""Memory API 测试。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.memory.memory_store import MemoryStore
from app.memory.service import MemoryService
from app.memory.session_store import SessionStore
from app.memory.sqlite_store import SQLiteMemoryStore, SQLiteSessionStore, init_memory_db
from app.api.memory import init_memory_api
from app.runtime.store import init_db


# ─── 辅助 ─────────────────────────────────────────────────


async def _setup() -> tuple[MemoryService, any]:
    """初始化 Memory 模块并注册 API。"""
    db = await init_db()
    await init_memory_db(db)

    session_store = SQLiteSessionStore(db)
    memory_store = SQLiteMemoryStore(db)
    service = MemoryService(session_store, memory_store)
    init_memory_api(service)

    return service, db


# ─── 会话 API 测试 ────────────────────────────────────────


class TestSessionAPI:
    @pytest.mark.asyncio
    async def test_create_session(self) -> None:
        _, db = await _setup()

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/memory/sessions",
                json={"title": "测试会话"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "测试会话"
        assert data["session_id"]
        assert data["message_count"] == 0

        await db.close()

    @pytest.mark.asyncio
    async def test_list_sessions(self) -> None:
        service, db = await _setup()

        await service.create_session(title="会话1")
        await service.create_session(title="会话2")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/memory/sessions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["sessions"]) == 2

        await db.close()

    @pytest.mark.asyncio
    async def test_get_session(self) -> None:
        service, db = await _setup()
        session = await service.create_session(title="test")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/memory/sessions/{session.session_id}")

        assert resp.status_code == 200
        assert resp.json()["title"] == "test"

        await db.close()

    @pytest.mark.asyncio
    async def test_get_session_not_found(self) -> None:
        _, db = await _setup()

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/memory/sessions/nonexistent")

        assert resp.status_code == 404

        await db.close()

    @pytest.mark.asyncio
    async def test_delete_session(self) -> None:
        service, db = await _setup()
        session = await service.create_session(title="test")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/api/memory/sessions/{session.session_id}")

        assert resp.status_code == 204

        await db.close()


# ─── 消息 API 测试 ────────────────────────────────────────


class TestMessageAPI:
    @pytest.mark.asyncio
    async def test_add_message(self) -> None:
        service, db = await _setup()
        session = await service.create_session(title="test")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/memory/sessions/{session.session_id}/messages",
                json={"role": "user", "content": "你好"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "user"
        assert data["content"] == "你好"

        await db.close()

    @pytest.mark.asyncio
    async def test_get_messages(self) -> None:
        service, db = await _setup()
        session = await service.create_session(title="test")
        await service.add_message(session.session_id, "user", "你好")
        await service.add_message(session.session_id, "assistant", "你好！")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/memory/sessions/{session.session_id}/messages"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["messages"]) == 2

        await db.close()

    @pytest.mark.asyncio
    async def test_add_message_session_not_found(self) -> None:
        _, db = await _setup()

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/memory/sessions/nonexistent/messages",
                json={"role": "user", "content": "test"},
            )

        assert resp.status_code == 404

        await db.close()


# ─── 长期记忆 API 测试 ────────────────────────────────────


class TestMemoryAPI:
    @pytest.mark.asyncio
    async def test_create_memory(self) -> None:
        _, db = await _setup()

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/memory/memories",
                json={
                    "content": "用户偏好中文回复",
                    "category": "preference",
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "用户偏好中文回复"
        assert data["category"] == "preference"
        assert data["confidence"] == 1.0

        await db.close()

    @pytest.mark.asyncio
    async def test_list_memories(self) -> None:
        service, db = await _setup()
        await service.create_memory(content="记忆1", category="fact")
        await service.create_memory(content="记忆2", category="preference")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/memory/memories")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

        await db.close()

    @pytest.mark.asyncio
    async def test_get_memory(self) -> None:
        service, db = await _setup()
        entry = await service.create_memory(content="test", category="other")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/memory/memories/{entry.memory_id}")

        assert resp.status_code == 200
        assert resp.json()["content"] == "test"

        await db.close()

    @pytest.mark.asyncio
    async def test_update_memory(self) -> None:
        service, db = await _setup()
        entry = await service.create_memory(content="旧内容", category="other")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/memory/memories/{entry.memory_id}",
                json={"content": "新内容", "category": "fact"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "新内容"
        assert data["category"] == "fact"

        await db.close()

    @pytest.mark.asyncio
    async def test_delete_memory(self) -> None:
        service, db = await _setup()
        entry = await service.create_memory(content="test", category="other")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/api/memory/memories/{entry.memory_id}")

        assert resp.status_code == 204

        await db.close()


# ─── 搜索 API 测试 ────────────────────────────────────────


class TestSearchAPI:
    @pytest.mark.asyncio
    async def test_search(self) -> None:
        service, db = await _setup()
        await service.create_memory(content="用户偏好中文", category="preference")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/memory/search",
                json={"query": "中文"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any("中文" in r["content"] for r in data["results"])

        await db.close()

    @pytest.mark.asyncio
    async def test_search_messages(self) -> None:
        service, db = await _setup()
        session = await service.create_session(title="test")
        await service.add_message(session.session_id, "user", "我喜欢Python编程")

        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/memory/search",
                json={"query": "Python", "search_type": "messages"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any("Python" in r["content"] for r in data["results"])

        await db.close()
