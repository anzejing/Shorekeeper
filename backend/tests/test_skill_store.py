"""SkillStore 测试。"""

from __future__ import annotations

import pytest

from app.runtime.store import init_db
from app.skill.store import SQLiteSkillStore, init_skill_db


# ─── 辅助 ─────────────────────────────────────────────────


async def _make_store() -> tuple[SQLiteSkillStore, any]:
    db = await init_db()
    await init_skill_db(db)
    return SQLiteSkillStore(db), db


# ─── CRUD 测试 ────────────────────────────────────────────


class TestSkillStore:
    @pytest.mark.asyncio
    async def test_upsert_new(self) -> None:
        store, db = await _make_store()

        state = await store.upsert("memory", enabled=True)
        assert state.name == "memory"
        assert state.enabled is True

        await db.close()

    @pytest.mark.asyncio
    async def test_upsert_existing_preserves_state(self) -> None:
        store, db = await _make_store()

        # 首次创建
        await store.upsert("memory", enabled=False, config={"key": "value"})

        # 再次 upsert（不覆盖 enabled/config）
        state = await store.upsert("memory", enabled=True)
        assert state.enabled is False  # 保留原值
        assert state.config == {"key": "value"}  # 保留原值

        await db.close()

    @pytest.mark.asyncio
    async def test_get(self) -> None:
        store, db = await _make_store()

        await store.upsert("memory")
        state = await store.get("memory")

        assert state is not None
        assert state.name == "memory"

        await db.close()

    @pytest.mark.asyncio
    async def test_get_not_found(self) -> None:
        store, db = await _make_store()

        state = await store.get("nonexistent")
        assert state is None

        await db.close()

    @pytest.mark.asyncio
    async def test_list_all(self) -> None:
        store, db = await _make_store()

        await store.upsert("alpha")
        await store.upsert("beta")
        await store.upsert("gamma")

        states = await store.list()
        assert len(states) == 3

        await db.close()

    @pytest.mark.asyncio
    async def test_list_enabled_only(self) -> None:
        store, db = await _make_store()

        await store.upsert("alpha", enabled=True)
        await store.upsert("beta", enabled=False)
        await store.upsert("gamma", enabled=True)

        enabled = await store.list(enabled=True)
        assert len(enabled) == 2
        assert all(s.enabled for s in enabled)

        disabled = await store.list(enabled=False)
        assert len(disabled) == 1
        assert disabled[0].name == "beta"

        await db.close()

    @pytest.mark.asyncio
    async def test_update(self) -> None:
        store, db = await _make_store()

        await store.upsert("memory", enabled=True)
        updated = await store.update("memory", enabled=False, config={"new": True})

        assert updated.enabled is False
        assert updated.config == {"new": True}

        await db.close()

    @pytest.mark.asyncio
    async def test_update_not_found(self) -> None:
        store, db = await _make_store()

        with pytest.raises(KeyError):
            await store.update("nonexistent", enabled=False)

        await db.close()

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        store, db = await _make_store()

        await store.upsert("memory")
        deleted = await store.delete("memory")
        assert deleted is True

        state = await store.get("memory")
        assert state is None

        await db.close()

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        store, db = await _make_store()

        deleted = await store.delete("nonexistent")
        assert deleted is False

        await db.close()
