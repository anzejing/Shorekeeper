"""SessionStore 测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.memory.models import Session, SessionMessage
from app.memory.sqlite_store import SQLiteSessionStore, init_memory_db
from app.runtime.store import init_db


# ─── 辅助 ─────────────────────────────────────────────────


async def _make_store() -> tuple[SQLiteSessionStore, any]:
    """创建内存数据库和 SessionStore。"""
    db = await init_db()
    await init_memory_db(db)
    return SQLiteSessionStore(db), db


# ─── Session CRUD ─────────────────────────────────────────


class TestSessionCRUD:
    @pytest.mark.asyncio
    async def test_create_session(self) -> None:
        store, db = await _make_store()

        session = await store.create_session(title="测试会话")
        assert session.title == "测试会话"
        assert session.session_id
        assert session.metadata == {}

        await db.close()

    @pytest.mark.asyncio
    async def test_create_session_with_metadata(self) -> None:
        store, db = await _make_store()

        session = await store.create_session(title="test", metadata={"key": "value"})
        assert session.metadata == {"key": "value"}

        await db.close()

    @pytest.mark.asyncio
    async def test_get_session(self) -> None:
        store, db = await _make_store()

        created = await store.create_session(title="test")
        loaded = await store.get_session(created.session_id)

        assert loaded is not None
        assert loaded.session_id == created.session_id
        assert loaded.title == "test"

        await db.close()

    @pytest.mark.asyncio
    async def test_get_session_not_found(self) -> None:
        store, db = await _make_store()

        result = await store.get_session("nonexistent")
        assert result is None

        await db.close()

    @pytest.mark.asyncio
    async def test_list_sessions(self) -> None:
        store, db = await _make_store()

        for i in range(5):
            await store.create_session(title=f"会话{i}")

        sessions, total = await store.list_sessions(limit=3, offset=0)
        assert total == 5
        assert len(sessions) == 3

        # 验证倒序（最新的在前）
        assert sessions[0].title == "会话4"

        await db.close()

    @pytest.mark.asyncio
    async def test_list_sessions_offset(self) -> None:
        store, db = await _make_store()

        for i in range(5):
            await store.create_session(title=f"会话{i}")

        sessions, total = await store.list_sessions(limit=3, offset=3)
        assert total == 5
        assert len(sessions) == 2

        await db.close()

    @pytest.mark.asyncio
    async def test_update_session(self) -> None:
        store, db = await _make_store()

        created = await store.create_session(title="原标题")
        updated = await store.update_session(
            created.session_id, title="新标题"
        )

        assert updated.title == "新标题"
        assert updated.updated_at >= created.updated_at

        await db.close()

    @pytest.mark.asyncio
    async def test_update_session_not_found(self) -> None:
        store, db = await _make_store()

        with pytest.raises(KeyError):
            await store.update_session("nonexistent", title="test")

        await db.close()

    @pytest.mark.asyncio
    async def test_delete_session(self) -> None:
        store, db = await _make_store()

        created = await store.create_session(title="test")
        deleted = await store.delete_session(created.session_id)
        assert deleted is True

        result = await store.get_session(created.session_id)
        assert result is None

        await db.close()

    @pytest.mark.asyncio
    async def test_delete_session_not_found(self) -> None:
        store, db = await _make_store()

        deleted = await store.delete_session("nonexistent")
        assert deleted is False

        await db.close()


# ─── Message 操作 ─────────────────────────────────────────


class TestMessageOperations:
    @pytest.mark.asyncio
    async def test_save_message(self) -> None:
        store, db = await _make_store()

        session = await store.create_session(title="test")
        msg = await store.save_message(
            session_id=session.session_id,
            role="user",
            content="你好",
        )

        assert msg.role == "user"
        assert msg.content == "你好"
        assert msg.session_id == session.session_id

        await db.close()

    @pytest.mark.asyncio
    async def test_save_message_session_not_found(self) -> None:
        store, db = await _make_store()

        with pytest.raises(KeyError):
            await store.save_message(
                session_id="nonexistent",
                role="user",
                content="test",
            )

        await db.close()

    @pytest.mark.asyncio
    async def test_get_messages(self) -> None:
        store, db = await _make_store()

        session = await store.create_session(title="test")
        await store.save_message(session.session_id, "user", "消息1")
        await store.save_message(session.session_id, "assistant", "回复1")
        await store.save_message(session.session_id, "user", "消息2")

        messages, total = await store.get_messages(session.session_id)
        assert total == 3
        assert len(messages) == 3

        # 验证正序
        assert messages[0].content == "消息1"
        assert messages[1].content == "回复1"
        assert messages[2].content == "消息2"

        await db.close()

    @pytest.mark.asyncio
    async def test_get_messages_pagination(self) -> None:
        store, db = await _make_store()

        session = await store.create_session(title="test")
        for i in range(10):
            await store.save_message(session.session_id, "user", f"消息{i}")

        messages, total = await store.get_messages(
            session.session_id, limit=3, offset=2
        )
        assert total == 10
        assert len(messages) == 3
        assert messages[0].content == "消息2"

        await db.close()

    @pytest.mark.asyncio
    async def test_get_messages_before(self) -> None:
        store, db = await _make_store()

        session = await store.create_session(title="test")
        msg1 = await store.save_message(session.session_id, "user", "消息1")
        await store.save_message(session.session_id, "user", "消息2")
        await store.save_message(session.session_id, "user", "消息3")

        # 获取 msg1 之前的消息（实际上没有，因为 msg1 是第一条）
        messages, total = await store.get_messages(
            session.session_id, before=msg1.created_at
        )
        assert total == 0

        await db.close()

    @pytest.mark.asyncio
    async def test_get_message_count(self) -> None:
        store, db = await _make_store()

        session = await store.create_session(title="test")
        assert await store.get_message_count(session.session_id) == 0

        await store.save_message(session.session_id, "user", "消息1")
        assert await store.get_message_count(session.session_id) == 1

        await store.save_message(session.session_id, "assistant", "回复1")
        assert await store.get_message_count(session.session_id) == 2

        await db.close()


# ─── 级联删除 ─────────────────────────────────────────────


class TestCascadeDelete:
    @pytest.mark.asyncio
    async def test_delete_session_removes_messages(self) -> None:
        store, db = await _make_store()

        session = await store.create_session(title="test")
        await store.save_message(session.session_id, "user", "消息1")
        await store.save_message(session.session_id, "assistant", "回复1")

        # 删除会话
        await store.delete_session(session.session_id)

        # 消息也应被删除
        messages, total = await store.get_messages(session.session_id)
        assert total == 0
        assert messages == []

        await db.close()
