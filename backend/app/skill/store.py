"""SkillStore — Skill 状态的 SQLite 持久化。

只存储运行时状态（enabled, config），不存储文件内容。
文件内容由 SkillLoader 从 SKILL.md 读取。

表结构：
- skill_states: Skill 运行时状态
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.skill.models import SkillState

# ─── 建表 SQL ─────────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS skill_states (
    name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    config TEXT NOT NULL DEFAULT '{}',
    installed_at TEXT NOT NULL
);
"""

# ─── 辅助函数 ─────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_to_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


# ─── SQLiteSkillStore ────────────────────────────────────


class SQLiteSkillStore:
    """Skill 状态的 SQLite 持久化。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self, name: str) -> SkillState | None:
        """获取 Skill 状态。"""
        cursor = await self._db.execute(
            "SELECT * FROM skill_states WHERE name = ?", (name,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_state(row)

    async def list(
        self,
        enabled: bool | None = None,
    ) -> list[SkillState]:
        """列出 Skill 状态。"""
        if enabled is not None:
            cursor = await self._db.execute(
                "SELECT * FROM skill_states WHERE enabled = ? ORDER BY name",
                (1 if enabled else 0,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM skill_states ORDER BY name"
            )
        rows = await cursor.fetchall()
        return [_row_to_state(row) for row in rows]

    async def upsert(
        self,
        name: str,
        enabled: bool = True,
        config: dict[str, Any] | None = None,
    ) -> SkillState:
        """创建或更新 Skill 状态。

        如果已存在，不覆盖 enabled/config（保留用户设置）。
        """
        now = _now_iso()
        existing = await self.get(name)

        if existing:
            # 已存在，只更新 installed_at（标记为仍存在）
            await self._db.execute(
                "UPDATE skill_states SET installed_at = ? WHERE name = ?",
                (now, name),
            )
            await self._db.commit()
            return existing

        # 新建
        state = SkillState(
            name=name,
            enabled=enabled,
            config=config or {},
            installed_at=_iso_to_dt(now),
        )
        await self._db.execute(
            """INSERT INTO skill_states (name, enabled, config, installed_at)
            VALUES (?, ?, ?, ?)""",
            (name, 1 if enabled else 0, json.dumps(state.config), now),
        )
        await self._db.commit()
        return state

    async def update(self, name: str, **fields: Any) -> SkillState:
        """更新 Skill 状态字段。"""
        existing = await self.get(name)
        if existing is None:
            raise KeyError(f"Skill 不存在: {name}")

        updates: list[str] = []
        params: list[Any] = []

        if "enabled" in fields:
            updates.append("enabled = ?")
            params.append(1 if fields["enabled"] else 0)

        if "config" in fields:
            updates.append("config = ?")
            params.append(json.dumps(fields["config"]))

        if not updates:
            return existing

        params.append(name)
        await self._db.execute(
            f"UPDATE skill_states SET {', '.join(updates)} WHERE name = ?",
            params,
        )
        await self._db.commit()

        return await self.get(name)  # type: ignore[return-value]

    async def delete(self, name: str) -> bool:
        """删除 Skill 状态。"""
        cursor = await self._db.execute(
            "DELETE FROM skill_states WHERE name = ?", (name,)
        )
        await self._db.commit()
        return cursor.rowcount > 0


# ─── 行转模型 ─────────────────────────────────────────────


def _row_to_state(row: aiosqlite.Row) -> SkillState:
    return SkillState(
        name=row["name"],
        enabled=bool(row["enabled"]),
        config=json.loads(row["config"]),
        installed_at=_iso_to_dt(row["installed_at"]),
    )


# ─── 初始化 ───────────────────────────────────────────────


async def init_skill_db(db: aiosqlite.Connection) -> None:
    """在已有数据库连接上初始化 Skill 表。"""
    await db.executescript(_CREATE_TABLES)
    await db.commit()
