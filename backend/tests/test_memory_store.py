"""MemoryStore 测试。"""

from __future__ import annotations

import pytest

from app.memory.sqlite_store import SQLiteMemoryStore, init_memory_db
from app.runtime.store import init_db


# ─── 辅助 ─────────────────────────────────────────────────


async def _make_store() -> tuple[SQLiteMemoryStore, any]:
    """创建内存数据库和 MemoryStore。"""
    db = await init_db()
    await init_memory_db(db)
    return SQLiteMemoryStore(db), db


# ─── CRUD 测试 ────────────────────────────────────────────


class TestMemoryCRUD:
    @pytest.mark.asyncio
    async def test_create_memory(self) -> None:
        store, db = await _make_store()

        entry = await store.create(
            content="用户偏好中文回复",
            category="preference",
        )

        assert entry.content == "用户偏好中文回复"
        assert entry.category == "preference"
        assert entry.confidence == 1.0
        assert entry.source_session_id is None

        await db.close()

    @pytest.mark.asyncio
    async def test_create_memory_with_source(self) -> None:
        store, db = await _make_store()

        entry = await store.create(
            content="用户是开发者",
            category="fact",
            source_session_id="sess-123",
            confidence=0.8,
        )

        assert entry.source_session_id == "sess-123"
        assert entry.confidence == 0.8

        await db.close()

    @pytest.mark.asyncio
    async def test_get_memory(self) -> None:
        store, db = await _make_store()

        created = await store.create(content="test", category="other")
        loaded = await store.get(created.memory_id)

        assert loaded is not None
        assert loaded.memory_id == created.memory_id
        assert loaded.content == "test"

        await db.close()

    @pytest.mark.asyncio
    async def test_get_memory_not_found(self) -> None:
        store, db = await _make_store()

        result = await store.get("nonexistent")
        assert result is None

        await db.close()

    @pytest.mark.asyncio
    async def test_list_memories(self) -> None:
        store, db = await _make_store()

        await store.create(content="偏好1", category="preference")
        await store.create(content="事实1", category="fact")
        await store.create(content="偏好2", category="preference")

        entries, total = await store.list()
        assert total == 3
        assert len(entries) == 3

        await db.close()

    @pytest.mark.asyncio
    async def test_list_memories_by_category(self) -> None:
        store, db = await _make_store()

        await store.create(content="偏好1", category="preference")
        await store.create(content="事实1", category="fact")
        await store.create(content="偏好2", category="preference")

        entries, total = await store.list(category="preference")
        assert total == 2
        assert all(e.category == "preference" for e in entries)

        await db.close()

    @pytest.mark.asyncio
    async def test_list_memories_pagination(self) -> None:
        store, db = await _make_store()

        for i in range(10):
            await store.create(content=f"记忆{i}", category="other")

        entries, total = await store.list(limit=3, offset=5)
        assert total == 10
        assert len(entries) == 3

        await db.close()

    @pytest.mark.asyncio
    async def test_update_memory(self) -> None:
        store, db = await _make_store()

        created = await store.create(content="旧内容", category="other")
        updated = await store.update(
            created.memory_id, content="新内容", category="fact"
        )

        assert updated.content == "新内容"
        assert updated.category == "fact"
        assert updated.updated_at >= created.updated_at

        await db.close()

    @pytest.mark.asyncio
    async def test_update_memory_not_found(self) -> None:
        store, db = await _make_store()

        with pytest.raises(KeyError):
            await store.update("nonexistent", content="test")

        await db.close()

    @pytest.mark.asyncio
    async def test_delete_memory(self) -> None:
        store, db = await _make_store()

        created = await store.create(content="test", category="other")
        deleted = await store.delete(created.memory_id)
        assert deleted is True

        result = await store.get(created.memory_id)
        assert result is None

        await db.close()

    @pytest.mark.asyncio
    async def test_delete_memory_not_found(self) -> None:
        store, db = await _make_store()

        deleted = await store.delete("nonexistent")
        assert deleted is False

        await db.close()


# ─── 搜索测试 ─────────────────────────────────────────────


class TestMemorySearch:
    @pytest.mark.asyncio
    async def test_search_basic(self) -> None:
        store, db = await _make_store()

        await store.create(content="用户偏好中文回复", category="preference")
        await store.create(content="用户是Python开发者", category="fact")
        await store.create(content="今天天气不错", category="other")

        results = await store.search("中文")
        assert len(results) == 1
        assert "中文" in results[0].content

        await db.close()

    @pytest.mark.asyncio
    async def test_search_multiple_keywords(self) -> None:
        store, db = await _make_store()

        await store.create(content="用户偏好中文回复", category="preference")
        await store.create(content="用户喜欢Python编程", category="fact")
        await store.create(content="用户是中文开发者", category="fact")

        results = await store.search("用户 开发者")
        assert len(results) >= 1
        # 应该能找到同时包含两个关键词的结果
        found = any("用户" in r.content and "开发者" in r.content for r in results)
        assert found

        await db.close()

    @pytest.mark.asyncio
    async def test_search_with_session_filter(self) -> None:
        store, db = await _make_store()

        await store.create(
            content="用户偏好中文",
            category="preference",
            source_session_id="sess-1",
        )
        await store.create(
            content="用户偏好英文",
            category="preference",
            source_session_id="sess-2",
        )

        results = await store.search("偏好", session_id="sess-1")
        assert len(results) == 1
        assert results[0].source_session_id == "sess-1"

        await db.close()

    @pytest.mark.asyncio
    async def test_search_chinese_query_sliding_window(self) -> None:
        """中文整句查询通过滑动窗口命中。"""
        store, db = await _make_store()

        await store.create(content="用户喜欢用 pytest 写测试", category="preference")
        await store.create(content="用户喜欢用中文交流", category="preference")

        # 整句查询（无空格）也能命中“写测试”片段
        results = await store.search("你还记得我喜欢用什么写测试吗")
        assert any("pytest" in r.content for r in results)

        await db.close()

    @pytest.mark.asyncio
    async def test_search_ranked_by_match_count(self) -> None:
        """命中关键词多的结果排在前面。"""
        store, db = await _make_store()

        await store.create(content="用户喜欢写测试", category="preference")
        await store.create(
            content="用户喜欢写测试 用 pytest 框架", category="preference"
        )

        results = await store.search("pytest 测试")
        assert len(results) >= 2
        # 同时命中 pytest + 测试 的结果应该排在最前
        assert "pytest" in results[0].content

        await db.close()

    @pytest.mark.asyncio
    async def test_search_empty_query(self) -> None:
        """空查询返回空列表。"""
        store, db = await _make_store()

        await store.create(content="用户偏好中文回复", category="preference")

        results = await store.search("   ")
        assert results == []

        await db.close()

    @pytest.mark.asyncio
    async def test_search_empty_query(self) -> None:
        store, db = await _make_store()

        await store.create(content="test", category="other")
        results = await store.search("")
        assert results == []

        await db.close()

    @pytest.mark.asyncio
    async def test_search_no_results(self) -> None:
        store, db = await _make_store()

        await store.create(content="中文回复", category="other")
        results = await store.search("英文")
        assert results == []

        await db.close()
