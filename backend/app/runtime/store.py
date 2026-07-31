"""SQLite 持久化实现。

实现 RunStore、EventStore、CheckpointStore 的 SQLite 版本。
使用 aiosqlite 异步驱动，JSON 序列化 dataclass。

表结构：
- runs: Run 状态
- run_events: 事件日志
- checkpoints: 检查点快照
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.runtime.checkpoint import CheckpointStore
from app.runtime.events import RuntimeEvent
from app.runtime.models import (
    Checkpoint,
    Message,
    PendingWrite,
    Role,
    RunId,
    RunSnapshot,
    RunStatus,
    Usage,
)
from app.runtime.run_store import RunStore
from app.runtime.state import VersionConflictError

# ─── 建表 SQL ─────────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    version INTEGER NOT NULL DEFAULT 1,
    current_step INTEGER NOT NULL DEFAULT 0,
    max_steps INTEGER NOT NULL DEFAULT 20,
    suspension_id TEXT,
    execution_attempt INTEGER NOT NULL DEFAULT 0,
    messages TEXT NOT NULL DEFAULT '[]',
    usage TEXT NOT NULL DEFAULT '{}',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    execution_attempt INTEGER NOT NULL DEFAULT 0,
    causal_parent_id TEXT,
    payload TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    UNIQUE(run_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_run_events_run_id_sequence
    ON run_events(run_id, sequence);

CREATE INDEX IF NOT EXISTS idx_run_events_type
    ON run_events(event_type);

CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    state TEXT NOT NULL,
    pending_writes TEXT NOT NULL DEFAULT '[]',
    schema_version INTEGER NOT NULL DEFAULT 1,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id_step
    ON checkpoints(run_id, step DESC);
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


def _usage_to_json(usage: Usage) -> str:
    """Usage 序列化为 JSON。"""
    return json.dumps(asdict(usage))


def _json_to_usage(data: str) -> Usage:
    """JSON 反序列化为 Usage。"""
    d = json.loads(data)
    return Usage(**d)


def _messages_to_json(messages: list[Message]) -> str:
    """Message 列表序列化为 JSON。"""
    result = []
    for msg in messages:
        d = {
            "role": msg.role.value,
            "content": msg.content,
            "timestamp": _dt_to_iso(msg.timestamp),
            "metadata": msg.metadata,
        }
        result.append(d)
    return json.dumps(result)


def _json_to_messages(data: str) -> list[Message]:
    """JSON 反序列化为 Message 列表。"""
    raw = json.loads(data)
    result = []
    for d in raw:
        msg = Message(
            role=Role(d["role"]),
            content=d["content"],
            timestamp=_iso_to_dt(d.get("timestamp")) or datetime.now(timezone.utc),
            metadata=d.get("metadata", {}),
        )
        result.append(msg)
    return result


def _serialize_event(event: RuntimeEvent) -> dict[str, Any]:
    """将事件序列化为可存储的 dict。"""
    d = asdict(event)
    # datetime 转 ISO 字符串
    if "timestamp" in d and isinstance(d["timestamp"], datetime):
        d["timestamp"] = _dt_to_iso(d["timestamp"])
    return d


# ─── SQLiteRunStore ───────────────────────────────────────


class SQLiteRunStore:
    """Run 状态的 SQLite 持久化。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def save(self, snapshot: RunSnapshot) -> None:
        """保存或更新 Run 快照。乐观锁：version 必须匹配。"""
        now = _now_iso()

        # 尝试更新
        cursor = await self._db.execute(
            """UPDATE runs SET
                session_id = ?,
                agent_id = ?,
                status = ?,
                version = version + 1,
                current_step = ?,
                max_steps = ?,
                suspension_id = ?,
                execution_attempt = ?,
                messages = ?,
                usage = ?,
                metadata = ?,
                updated_at = ?,
                completed_at = ?
            WHERE id = ? AND version = ?""",
            (
                snapshot.session_id,
                snapshot.agent_id,
                snapshot.status.value,
                snapshot.current_step,
                snapshot.max_steps,
                snapshot.suspension_id,
                snapshot.execution_attempt,
                _messages_to_json(snapshot.messages),
                _usage_to_json(snapshot.usage),
                json.dumps(snapshot.metadata),
                now,
                _dt_to_iso(snapshot.completed_at),
                snapshot.run_id,
                snapshot.version,
            ),
        )

        if cursor.rowcount == 0:
            # 不存在或版本不匹配，检查是否存在
            existing = await self.get(RunId(snapshot.run_id))
            if existing is not None:
                raise VersionConflictError(
                    snapshot.run_id, snapshot.version, existing.version
                )
            # 不存在，插入
            await self._db.execute(
                """INSERT INTO runs (
                    id, session_id, agent_id, status, version,
                    current_step, max_steps, suspension_id, execution_attempt,
                    messages, usage, metadata, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot.run_id,
                    snapshot.session_id,
                    snapshot.agent_id,
                    snapshot.status.value,
                    snapshot.version,
                    snapshot.current_step,
                    snapshot.max_steps,
                    snapshot.suspension_id,
                    snapshot.execution_attempt,
                    _messages_to_json(snapshot.messages),
                    _usage_to_json(snapshot.usage),
                    json.dumps(snapshot.metadata),
                    _dt_to_iso(snapshot.created_at) or now,
                    now,
                    _dt_to_iso(snapshot.completed_at),
                ),
            )

        await self._db.commit()

    async def get(self, run_id: RunId) -> RunSnapshot | None:
        """按 ID 查询 Run。"""
        cursor = await self._db.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_snapshot(row)

    async def list_active(self) -> list[RunSnapshot]:
        """查询所有活跃 Run。"""
        cursor = await self._db.execute(
            """SELECT * FROM runs WHERE status NOT IN ('completed', 'cancelled', 'terminated', 'failed')"""
        )
        rows = await cursor.fetchall()
        return [_row_to_snapshot(row) for row in rows]


def _row_to_snapshot(row: aiosqlite.Row) -> RunSnapshot:
    """将数据库行转换为 RunSnapshot。"""
    return RunSnapshot(
        run_id=row["id"],
        session_id=row["session_id"],
        agent_id=row["agent_id"],
        status=RunStatus(row["status"]),
        version=row["version"],
        messages=_json_to_messages(row["messages"]),
        current_step=row["current_step"],
        max_steps=row["max_steps"],
        usage=_json_to_usage(row["usage"]),
        suspension_id=row["suspension_id"],
        execution_attempt=row["execution_attempt"],
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_iso_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
        completed_at=_iso_to_dt(row["completed_at"]),
        metadata=json.loads(row["metadata"]),
    )


# ─── SQLiteEventStore ─────────────────────────────────────


class SQLiteEventStore:
    """事件日志的 SQLite 持久化。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def save(self, event: RuntimeEvent) -> None:
        """保存一个事件。"""
        payload = _serialize_event(event)
        await self._db.execute(
            """INSERT OR IGNORE INTO run_events (
                id, run_id, session_id, sequence, event_type,
                schema_version, execution_attempt, causal_parent_id,
                payload, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.run_id,
                event.session_id,
                event.sequence,
                event.event_type.value,
                event.schema_version,
                event.execution_attempt,
                event.causal_parent_id,
                json.dumps(payload),
                _dt_to_iso(event.timestamp),
            ),
        )
        await self._db.commit()

    async def list_by_run(
        self, run_id: RunId, after_sequence: int = -1
    ) -> list[RuntimeEvent]:
        """按 run_id 查询事件，按 sequence 排序。

        Args:
            run_id: Run ID。
            after_sequence: 只返回 sequence > after_sequence 的事件。

        Returns:
            事件列表。
        """
        cursor = await self._db.execute(
            """SELECT * FROM run_events
            WHERE run_id = ? AND sequence > ?
            ORDER BY sequence ASC""",
            (run_id, after_sequence),
        )
        rows = await cursor.fetchall()
        return [_row_to_event(row) for row in rows]


_EVENT_TYPE_MAP: dict[str, type] = {}


def _get_event_class(event_type: str) -> type:
    """根据 event_type 字符串获取对应的事件子类。"""
    if not _EVENT_TYPE_MAP:
        # 延迟导入，避免循环依赖
        from app.runtime.events import (
            ArtifactCreated,
            CheckpointCreated,
            ModelReasoningDelta,
            ModelRequestStarted,
            ModelResponseCompleted,
            ModelTextDelta,
            ModelToolCallDelta,
            RunCancelled,
            RunCancellationRequested,
            RunCompleted,
            RunCreated,
            RunFailed,
            RunResumed,
            RunStarted,
            RunStateChanged,
            RunSuspended,
            RunTerminated,
            ToolApprovalRequested,
            ToolCallModified,
            ToolCallProposed,
            ToolExecutionCompleted,
            ToolExecutionFailed,
            ToolExecutionProgress,
            ToolExecutionStarted,
            UsageUpdated,
        )

        _EVENT_TYPE_MAP.update(
            {
                "run_created": RunCreated,
                "run_started": RunStarted,
                "run_state_changed": RunStateChanged,
                "run_completed": RunCompleted,
                "run_failed": RunFailed,
                "run_suspended": RunSuspended,
                "run_resumed": RunResumed,
                "run_cancellation_requested": RunCancellationRequested,
                "run_cancelled": RunCancelled,
                "run_terminated": RunTerminated,
                "model_request_started": ModelRequestStarted,
                "model_text_delta": ModelTextDelta,
                "model_reasoning_delta": ModelReasoningDelta,
                "model_tool_call_delta": ModelToolCallDelta,
                "model_response_completed": ModelResponseCompleted,
                "tool_call_proposed": ToolCallProposed,
                "tool_call_modified": ToolCallModified,
                "tool_approval_requested": ToolApprovalRequested,
                "tool_execution_started": ToolExecutionStarted,
                "tool_execution_progress": ToolExecutionProgress,
                "tool_execution_completed": ToolExecutionCompleted,
                "tool_execution_failed": ToolExecutionFailed,
                "checkpoint_created": CheckpointCreated,
                "usage_updated": UsageUpdated,
                "artifact_created": ArtifactCreated,
            }
        )
    return _EVENT_TYPE_MAP.get(event_type, RuntimeEvent)


def _row_to_event(row: aiosqlite.Row) -> RuntimeEvent:
    """将数据库行转换为 RuntimeEvent 子类。"""
    payload = json.loads(row["payload"])
    # 恢复 datetime
    if "timestamp" in payload and isinstance(payload["timestamp"], str):
        payload["timestamp"] = datetime.fromisoformat(payload["timestamp"])
    # 恢复 event_type 枚举
    from app.runtime.events import EventType

    event_type_str = payload["event_type"]
    payload["event_type"] = EventType(event_type_str)
    # 使用正确的子类构造
    event_cls = _get_event_class(event_type_str)
    return event_cls(**payload)


# ─── SQLiteCheckpointStore ────────────────────────────────


class SQLiteCheckpointStore:
    """检查点的 SQLite 持久化。实现 CheckpointStore Protocol。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def save(self, checkpoint: Checkpoint) -> None:
        """保存一个 checkpoint。"""
        state = asdict(checkpoint.state)
        # 序列化 datetime 字段
        for key in ("created_at", "updated_at", "completed_at"):
            if state.get(key) is not None:
                state[key] = _dt_to_iso(state[key])
        # 序列化 messages
        state["messages"] = [
            {
                "role": m.role.value,
                "content": m.content,
                "timestamp": _dt_to_iso(m.timestamp),
                "metadata": m.metadata,
            }
            for m in checkpoint.state.messages
        ]
        # 序列化 usage
        state["usage"] = asdict(checkpoint.state.usage)
        # 序列化 status
        state["status"] = state["status"].value if isinstance(state["status"], RunStatus) else state["status"]

        pending = [asdict(pw) for pw in checkpoint.pending_writes]

        await self._db.execute(
            """INSERT OR REPLACE INTO checkpoints (
                id, run_id, step, state, pending_writes,
                schema_version, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                checkpoint.id,
                checkpoint.run_id,
                checkpoint.step,
                json.dumps(state),
                json.dumps(pending),
                checkpoint.schema_version,
                _dt_to_iso(checkpoint.timestamp),
            ),
        )
        await self._db.commit()

    async def load_latest(self, run_id: RunId) -> Checkpoint | None:
        """加载指定 Run 的最新 checkpoint。"""
        cursor = await self._db.execute(
            """SELECT * FROM checkpoints
            WHERE run_id = ?
            ORDER BY step DESC
            LIMIT 1""",
            (run_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_checkpoint(row)


def _row_to_checkpoint(row: aiosqlite.Row) -> Checkpoint:
    """将数据库行转换为 Checkpoint。"""
    state = json.loads(row["state"])
    pending = json.loads(row["pending_writes"])

    # 恢复 RunSnapshot
    snapshot = RunSnapshot(
        run_id=state["run_id"],
        session_id=state["session_id"],
        agent_id=state["agent_id"],
        status=RunStatus(state["status"]) if isinstance(state["status"], str) else state["status"],
        version=state["version"],
        messages=[
            Message(
                role=Role(m["role"]),
                content=m["content"],
                timestamp=_iso_to_dt(m.get("timestamp")) or datetime.now(timezone.utc),
                metadata=m.get("metadata", {}),
            )
            for m in state["messages"]
        ],
        current_step=state["current_step"],
        max_steps=state["max_steps"],
        usage=Usage(**state["usage"]),
        suspension_id=state.get("suspension_id"),
        execution_attempt=state["execution_attempt"],
        created_at=_iso_to_dt(state.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_iso_to_dt(state.get("updated_at")) or datetime.now(timezone.utc),
        completed_at=_iso_to_dt(state.get("completed_at")),
        metadata=state.get("metadata", {}),
    )

    return Checkpoint(
        id=row["id"],
        run_id=row["run_id"],
        step=row["step"],
        state=snapshot,
        pending_writes=[PendingWrite(**pw) for pw in pending],
        timestamp=_iso_to_dt(row["timestamp"]) or datetime.now(timezone.utc),
        schema_version=row["schema_version"],
    )


# ─── 初始化 ───────────────────────────────────────────────


async def init_db(db_path: str = ":memory:") -> aiosqlite.Connection:
    """初始化 SQLite 数据库，建表。

    Args:
        db_path: 数据库文件路径，":memory:" 为内存数据库。

    Returns:
        数据库连接。
    """
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.executescript(_CREATE_TABLES)
    await db.commit()
    return db
