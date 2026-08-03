"""SQLite 持久化实现。

实现 SessionStore 和 MemoryStore 的 SQLite 版本。
使用 aiosqlite 异步驱动，与 Runtime 的 SQLiteStore 风格一致。

表结构：
- memory_sessions: 会话
- memory_messages: 会话消息
- memory_entries: 长期记忆
- memory_entries_fts: 长期记忆全文搜索索引
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.memory.models import MemoryEntry, Session, SessionMessage

# ─── 建表 SQL ─────────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS memory_sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_sessions_updated_at
    ON memory_sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS memory_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES memory_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_messages_session_id_created_at
    ON memory_messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    source_session_id TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_entries_category
    ON memory_entries(category);

CREATE INDEX IF NOT EXISTS idx_memory_entries_source_session_id
    ON memory_entries(source_session_id);

"""

# ─── 辅助函数 ─────────────────────────────────────────────


def _now_iso() -> str:
    """当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _dt_to_iso(dt: datetime | None) -> str | None:
    """datetime 转 ISO 字符串。"""
    if dt is None:
        return None
    return dt.isoformat()


def _iso_to_dt(iso: str | None) -> datetime | None:
    """ISO 字符串转 datetime。"""
    if iso is None:
        return None
    return datetime.fromisoformat(iso)


# ─── SQLiteSessionStore ───────────────────────────────────


class SQLiteSessionStore:
    """会话与消息的 SQLite 持久化。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def create_session(
        self,
        title: str,
        metadata: dict | None = None,
    ) -> Session:
        """创建新会话。"""
        from app.memory.models import new_session_id

        session_id = new_session_id()
        now = _now_iso()

        await self._db.execute(
            """INSERT INTO memory_sessions (id, title, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)""",
            (session_id, title, json.dumps(metadata or {}), now, now),
        )
        await self._db.commit()

        return Session(
            session_id=session_id,
            title=title,
            metadata=metadata or {},
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    async def get_session(self, session_id: str) -> Session | None:
        """获取会话。"""
        cursor = await self._db.execute(
            "SELECT * FROM memory_sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_session(row)

    async def list_sessions(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Session], int]:
        """列出会话，按更新时间倒序。"""
        # 总数
        cursor = await self._db.execute("SELECT COUNT(*) FROM memory_sessions")
        total = (await cursor.fetchone())[0]

        # 分页查询
        cursor = await self._db.execute(
            """SELECT * FROM memory_sessions
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        sessions = [_row_to_session(row) for row in rows]

        return sessions, total

    async def update_session(
        self,
        session_id: str,
        **fields,
    ) -> Session:
        """更新会话字段。"""
        # 检查存在
        existing = await self.get_session(session_id)
        if existing is None:
            raise KeyError(f"会话不存在: {session_id}")

        updates: list[str] = []
        params: list[Any] = []

        if "title" in fields:
            updates.append("title = ?")
            params.append(fields["title"])

        if "metadata" in fields:
            updates.append("metadata = ?")
            params.append(json.dumps(fields["metadata"]))

        if not updates:
            return existing

        updates.append("updated_at = ?")
        params.append(_now_iso())
        params.append(session_id)

        await self._db.execute(
            f"UPDATE memory_sessions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await self._db.commit()

        return await self.get_session(session_id)  # type: ignore[return-value]

    async def delete_session(self, session_id: str) -> bool:
        """删除会话及其所有消息。"""
        # 先删消息（外键 CASCADE 也行，但显式更安全）
        await self._db.execute(
            "DELETE FROM memory_messages WHERE session_id = ?", (session_id,)
        )
        cursor = await self._db.execute(
            "DELETE FROM memory_sessions WHERE id = ?", (session_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> SessionMessage:
        """保存消息到会话。"""
        from app.memory.models import new_message_id

        # 检查会话存在
        session = await self.get_session(session_id)
        if session is None:
            raise KeyError(f"会话不存在: {session_id}")

        message_id = new_message_id()
        now = _now_iso()

        await self._db.execute(
            """INSERT INTO memory_messages (id, session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (message_id, session_id, role, content, json.dumps(metadata or {}), now),
        )

        # 更新会话的 updated_at
        await self._db.execute(
            "UPDATE memory_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        await self._db.commit()

        return SessionMessage(
            message_id=message_id,
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
            created_at=datetime.fromisoformat(now),
        )

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
        before: datetime | None = None,
    ) -> tuple[list[SessionMessage], int]:
        """获取会话消息，按时间正序。"""
        where = "WHERE session_id = ?"
        params: list[Any] = [session_id]

        if before is not None:
            where += " AND created_at < ?"
            params.append(_dt_to_iso(before))

        # 总数
        cursor = await self._db.execute(
            f"SELECT COUNT(*) FROM memory_messages {where}", params
        )
        total = (await cursor.fetchone())[0]

        # 分页查询
        cursor = await self._db.execute(
            f"""SELECT * FROM memory_messages {where}
            ORDER BY created_at ASC
            LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        rows = await cursor.fetchall()
        messages = [_row_to_message(row) for row in rows]

        return messages, total

    async def get_message_count(self, session_id: str) -> int:
        """获取会话的消息总数。"""
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM memory_messages WHERE session_id = ?",
            (session_id,),
        )
        return (await cursor.fetchone())[0]


# ─── SQLiteMemoryStore ────────────────────────────────────


class SQLiteMemoryStore:
    """长期记忆的 SQLite 持久化。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def create(
        self,
        content: str,
        category: str,
        source_session_id: str | None = None,
        confidence: float = 1.0,
    ) -> MemoryEntry:
        """创建长期记忆。"""
        from app.memory.models import new_memory_id

        memory_id = new_memory_id()
        now = _now_iso()

        await self._db.execute(
            """INSERT INTO memory_entries (id, content, category, source_session_id, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (memory_id, content, category, source_session_id, confidence, now, now),
        )
        await self._db.commit()

        return MemoryEntry(
            memory_id=memory_id,
            content=content,
            category=category,
            source_session_id=source_session_id,
            confidence=confidence,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    async def get(self, memory_id: str) -> MemoryEntry | None:
        """获取单条记忆。"""
        cursor = await self._db.execute(
            "SELECT * FROM memory_entries WHERE id = ?", (memory_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_memory(row)

    async def list(
        self,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryEntry], int]:
        """列出记忆，按更新时间倒序。"""
        where = ""
        params: list[Any] = []

        if category is not None:
            where = "WHERE category = ?"
            params.append(category)

        # 总数
        cursor = await self._db.execute(
            f"SELECT COUNT(*) FROM memory_entries {where}", params
        )
        total = (await cursor.fetchone())[0]

        # 分页查询
        cursor = await self._db.execute(
            f"""SELECT * FROM memory_entries {where}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
        rows = await cursor.fetchall()
        entries = [_row_to_memory(row) for row in rows]

        return entries, total

    async def update(
        self,
        memory_id: str,
        **fields,
    ) -> MemoryEntry:
        """更新记忆字段。"""
        existing = await self.get(memory_id)
        if existing is None:
            raise KeyError(f"记忆不存在: {memory_id}")

        updates: list[str] = []
        params: list[Any] = []

        if "content" in fields:
            updates.append("content = ?")
            params.append(fields["content"])

        if "category" in fields:
            updates.append("category = ?")
            params.append(fields["category"])

        if "confidence" in fields:
            updates.append("confidence = ?")
            params.append(fields["confidence"])

        if not updates:
            return existing

        updates.append("updated_at = ?")
        params.append(_now_iso())
        params.append(memory_id)

        await self._db.execute(
            f"UPDATE memory_entries SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await self._db.commit()

        return await self.get(memory_id)  # type: ignore[return-value]

    async def delete(self, memory_id: str) -> bool:
        """删除记忆。"""
        cursor = await self._db.execute(
            "DELETE FROM memory_entries WHERE id = ?", (memory_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """搜索长期记忆（LIKE 关键词匹配）。

        初版使用 LIKE 实现基本搜索，后续可引入 FTS5（需中文分词器）或向量搜索。
        """
        if not query.strip():
            return []

        # 对每个关键词做 LIKE 匹配（AND 语义）
        keywords = [w for w in query.split() if w]
        if not keywords:
            return []

        conditions = ["content LIKE ?"] * len(keywords)
        params: list[Any] = [f"%{w}%" for w in keywords]

        if session_id is not None:
            conditions.append("source_session_id = ?")
            params.append(session_id)

        where = " AND ".join(conditions)
        params.append(limit)

        cursor = await self._db.execute(
            f"""SELECT * FROM memory_entries
            WHERE {where}
            ORDER BY updated_at DESC
            LIMIT ?""",
            params,
        )
        rows = await cursor.fetchall()
        return [_row_to_memory(row) for row in rows]


# ─── 行转模型 ─────────────────────────────────────────────


def _row_to_session(row: aiosqlite.Row) -> Session:
    """将数据库行转换为 Session。"""
    return Session(
        session_id=row["id"],
        title=row["title"],
        metadata=json.loads(row["metadata"]),
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_iso_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
    )


def _row_to_message(row: aiosqlite.Row) -> SessionMessage:
    """将数据库行转换为 SessionMessage。"""
    return SessionMessage(
        message_id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        metadata=json.loads(row["metadata"]),
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
    )


def _row_to_memory(row: aiosqlite.Row) -> MemoryEntry:
    """将数据库行转换为 MemoryEntry。"""
    return MemoryEntry(
        memory_id=row["id"],
        content=row["content"],
        category=row["category"],
        source_session_id=row["source_session_id"],
        confidence=row["confidence"],
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_iso_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
    )


# ─── 初始化 ───────────────────────────────────────────────


async def init_memory_db(db: aiosqlite.Connection) -> None:
    """在已有数据库连接上初始化 Memory 表。

    Args:
        db: 已有的 aiosqlite.Connection。
    """
    await db.executescript(_CREATE_TABLES)
    await db.commit()
