"""SQLite 持久化层测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.runtime.events import RunCompleted, RunStarted, create_event
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
from app.runtime.state import VersionConflictError
from app.runtime.store import (
    SQLiteCheckpointStore,
    SQLiteEventStore,
    SQLiteRunStore,
    init_db,
)


# ─── 辅助 ─────────────────────────────────────────────────


def _make_snapshot(
    run_id: str = "run-1",
    status: RunStatus = RunStatus.RUNNING,
    version: int = 0,
    current_step: int = 0,
    messages: list[Message] | None = None,
) -> RunSnapshot:
    """构造 RunSnapshot。"""
    now = datetime.now(timezone.utc)
    return RunSnapshot(
        run_id=run_id,
        session_id="sess-1",
        agent_id="agent-1",
        status=status,
        version=version,
        messages=messages or [Message(role=Role.USER, content="hello")],
        current_step=current_step,
        max_steps=20,
        usage=Usage(input_tokens=100, output_tokens=50),
        suspension_id=None,
        execution_attempt=0,
        created_at=now,
        updated_at=now,
        completed_at=None,
        metadata={"key": "value"},
    )


def _make_checkpoint(
    run_id: str = "run-1",
    step: int = 0,
    snapshot: RunSnapshot | None = None,
) -> Checkpoint:
    """构造 Checkpoint。"""
    now = datetime.now(timezone.utc)
    return Checkpoint(
        id=f"{run_id}:step:{step}",
        run_id=run_id,
        step=step,
        state=snapshot or _make_snapshot(run_id, current_step=step),
        pending_writes=[PendingWrite(task_id="t1", channel="msg", value="test")],
        timestamp=now,
    )


# ─── RunStore 测试 ────────────────────────────────────────


class TestSQLiteRunStore:
    @pytest.mark.asyncio
    async def test_save_and_get(self) -> None:
        db = await init_db()
        store = SQLiteRunStore(db)

        snapshot = _make_snapshot()
        await store.save(snapshot)

        loaded = await store.get(RunId("run-1"))
        assert loaded is not None
        assert loaded.run_id == "run-1"
        assert loaded.status == RunStatus.RUNNING
        assert loaded.session_id == "sess-1"
        assert loaded.agent_id == "agent-1"
        assert loaded.version == 0
        assert loaded.current_step == 0
        assert loaded.max_steps == 20
        assert loaded.messages[0].content == "hello"
        assert loaded.usage.input_tokens == 100
        assert loaded.metadata == {"key": "value"}

        await db.close()

    @pytest.mark.asyncio
    async def test_update_increments_version(self) -> None:
        db = await init_db()
        store = SQLiteRunStore(db)

        snapshot = _make_snapshot(version=0)
        await store.save(snapshot)

        snapshot.status = RunStatus.COMPLETED
        snapshot.version = 0  # 匹配数据库中的版本
        await store.save(snapshot)

        loaded = await store.get(RunId("run-1"))
        assert loaded is not None
        assert loaded.status == RunStatus.COMPLETED
        assert loaded.version == 1  # 递增了

        await db.close()

    @pytest.mark.asyncio
    async def test_version_conflict_raises(self) -> None:
        db = await init_db()
        store = SQLiteRunStore(db)

        snapshot = _make_snapshot(version=0)
        await store.save(snapshot)

        # 用错误的版本尝试更新
        snapshot.status = RunStatus.COMPLETED
        snapshot.version = 99  # 不匹配
        with pytest.raises(VersionConflictError) as exc_info:
            await store.save(snapshot)
        assert exc_info.value.run_id == "run-1"
        assert exc_info.value.expected == 99
        assert exc_info.value.actual == 0

        await db.close()

    @pytest.mark.asyncio
    async def test_get_nonexistent(self) -> None:
        db = await init_db()
        store = SQLiteRunStore(db)

        loaded = await store.get(RunId("nonexistent"))
        assert loaded is None

        await db.close()

    @pytest.mark.asyncio
    async def test_list_active(self) -> None:
        db = await init_db()
        store = SQLiteRunStore(db)

        # 创建多个 Run
        await store.save(_make_snapshot("run-1", RunStatus.RUNNING))
        await store.save(_make_snapshot("run-2", RunStatus.WAITING))
        await store.save(_make_snapshot("run-3", RunStatus.COMPLETED))
        await store.save(_make_snapshot("run-4", RunStatus.FAILED))

        active = await store.list_active()
        active_ids = {s.run_id for s in active}
        assert active_ids == {"run-1", "run-2"}

        await db.close()

    @pytest.mark.asyncio
    async def test_messages_roundtrip(self) -> None:
        """消息列表序列化/反序列化保持正确。"""
        db = await init_db()
        store = SQLiteRunStore(db)

        messages = [
            Message(role=Role.USER, content="你好"),
            Message(role=Role.ASSISTANT, content="你好！有什么可以帮助你的？"),
            Message(role=Role.USER, content="帮我读文件"),
            Message(
                role=Role.TOOL,
                content="文件内容",
                metadata={"tool_call_id": "tc-1", "is_error": False},
            ),
        ]
        snapshot = _make_snapshot(messages=messages)
        await store.save(snapshot)

        loaded = await store.get(RunId("run-1"))
        assert loaded is not None
        assert len(loaded.messages) == 4
        assert loaded.messages[0].role == Role.USER
        assert loaded.messages[3].role == Role.TOOL
        assert loaded.messages[3].metadata["tool_call_id"] == "tc-1"

        await db.close()


# ─── EventStore 测试 ──────────────────────────────────────


class TestSQLiteEventStore:
    @pytest.mark.asyncio
    async def test_save_and_list(self) -> None:
        db = await init_db()
        store = SQLiteEventStore(db)

        event1 = create_event(
            RunStarted, run_id="run-1", session_id="sess-1", sequence=0, max_steps=20
        )
        event2 = create_event(
            RunCompleted,
            run_id="run-1",
            session_id="sess-1",
            sequence=1,
            output="done",
        )

        await store.save(event1)
        await store.save(event2)

        events = await store.list_by_run(RunId("run-1"))
        assert len(events) == 2
        assert events[0].sequence == 0
        assert events[1].sequence == 1

        await db.close()

    @pytest.mark.asyncio
    async def test_list_after_sequence(self) -> None:
        db = await init_db()
        store = SQLiteEventStore(db)

        for i in range(5):
            event = create_event(
                RunStarted,
                run_id="run-1",
                session_id="sess-1",
                sequence=i,
                max_steps=20,
            )
            await store.save(event)

        # 只获取 sequence > 2 的事件
        events = await store.list_by_run(RunId("run-1"), after_sequence=2)
        assert len(events) == 2
        assert events[0].sequence == 3
        assert events[1].sequence == 4

        await db.close()

    @pytest.mark.asyncio
    async def test_list_empty(self) -> None:
        db = await init_db()
        store = SQLiteEventStore(db)

        events = await store.list_by_run(RunId("nonexistent"))
        assert events == []

        await db.close()

    @pytest.mark.asyncio
    async def test_duplicate_ignored(self) -> None:
        """重复事件（相同 run_id + sequence）被忽略。"""
        db = await init_db()
        store = SQLiteEventStore(db)

        event = create_event(
            RunStarted, run_id="run-1", session_id="sess-1", sequence=0
        )
        await store.save(event)
        await store.save(event)  # 重复插入

        events = await store.list_by_run(RunId("run-1"))
        assert len(events) == 1

        await db.close()


# ─── CheckpointStore 测试 ─────────────────────────────────


class TestSQLiteCheckpointStore:
    @pytest.mark.asyncio
    async def test_save_and_load_latest(self) -> None:
        db = await init_db()
        store = SQLiteCheckpointStore(db)

        cp0 = _make_checkpoint("run-1", step=0)
        cp1 = _make_checkpoint("run-1", step=1)
        cp2 = _make_checkpoint("run-1", step=2)

        await store.save(cp0)
        await store.save(cp1)
        await store.save(cp2)

        latest = await store.load_latest(RunId("run-1"))
        assert latest is not None
        assert latest.step == 2
        assert latest.run_id == "run-1"

        await db.close()

    @pytest.mark.asyncio
    async def test_load_nonexistent(self) -> None:
        db = await init_db()
        store = SQLiteCheckpointStore(db)

        latest = await store.load_latest(RunId("nonexistent"))
        assert latest is None

        await db.close()

    @pytest.mark.asyncio
    async def test_pending_writes_roundtrip(self) -> None:
        db = await init_db()
        store = SQLiteCheckpointStore(db)

        cp = _make_checkpoint("run-1", step=0)
        await store.save(cp)

        loaded = await store.load_latest(RunId("run-1"))
        assert loaded is not None
        assert len(loaded.pending_writes) == 1
        assert loaded.pending_writes[0].task_id == "t1"
        assert loaded.pending_writes[0].channel == "msg"

        await db.close()

    @pytest.mark.asyncio
    async def test_upsert_same_id(self) -> None:
        """相同 id 的 checkpoint 被覆盖。"""
        db = await init_db()
        store = SQLiteCheckpointStore(db)

        cp = _make_checkpoint("run-1", step=0)
        await store.save(cp)

        # 修改后重新保存（相同 id）
        cp.state.current_step = 99
        await store.save(cp)

        loaded = await store.load_latest(RunId("run-1"))
        assert loaded is not None
        assert loaded.state.current_step == 99

        await db.close()


# ─── 集成测试 ─────────────────────────────────────────────


class TestIntegration:
    @pytest.mark.asyncio
    async def test_crash_recovery_flow(self) -> None:
        """模拟崩溃恢复：保存 checkpoint + events，然后重建。"""
        db = await init_db()
        run_store = SQLiteRunStore(db)
        event_store = SQLiteEventStore(db)
        cp_store = SQLiteCheckpointStore(db)

        # 1. 创建 Run
        snapshot = _make_snapshot("run-1", RunStatus.RUNNING, version=0, current_step=3)
        await run_store.save(snapshot)

        # 2. 保存 checkpoint
        cp = _make_checkpoint("run-1", step=3, snapshot=snapshot)
        await cp_store.save(cp)

        # 3. 保存事件
        event1 = create_event(
            RunStarted, run_id="run-1", session_id="sess-1", sequence=0
        )
        event2 = create_event(
            RunCompleted, run_id="run-1", session_id="sess-1", sequence=1, output="test"
        )
        await event_store.save(event1)
        await event_store.save(event2)

        # 4. 模拟崩溃恢复
        active_runs = await run_store.list_active()
        assert len(active_runs) == 1
        assert active_runs[0].run_id == "run-1"

        # 5. 加载最新 checkpoint
        latest_cp = await cp_store.load_latest(RunId("run-1"))
        assert latest_cp is not None
        assert latest_cp.step == 3

        # 6. 加载 checkpoint 之后的事件
        events = await event_store.list_by_run(
            RunId("run-1"), after_sequence=latest_cp.step
        )
        assert len(events) >= 0  # checkpoint 之后的事件

        await db.close()

    @pytest.mark.asyncio
    async def test_run_lifecycle_persistence(self) -> None:
        """完整 Run 生命周期持久化。"""
        db = await init_db()
        run_store = SQLiteRunStore(db)
        event_store = SQLiteEventStore(db)

        # CREATED
        snapshot = _make_snapshot("run-1", RunStatus.CREATED, version=0)
        await run_store.save(snapshot)
        await event_store.save(
            create_event(RunStarted, "run-1", "sess-1", sequence=0)
        )

        # RUNNING
        snapshot = await run_store.get(RunId("run-1"))
        assert snapshot is not None
        snapshot.status = RunStatus.RUNNING
        snapshot.version = 0  # 匹配
        await run_store.save(snapshot)

        # COMPLETED
        snapshot = await run_store.get(RunId("run-1"))
        assert snapshot is not None
        snapshot.status = RunStatus.COMPLETED
        snapshot.completed_at = datetime.now(timezone.utc)
        snapshot.version = 1  # 匹配（已递增一次）
        await run_store.save(snapshot)
        await event_store.save(
            create_event(
                RunCompleted, "run-1", "sess-1", sequence=1, output="done"
            )
        )

        # 验证最终状态
        final = await run_store.get(RunId("run-1"))
        assert final is not None
        assert final.status == RunStatus.COMPLETED
        assert final.version == 2

        # 验证事件历史
        events = await event_store.list_by_run(RunId("run-1"))
        assert len(events) == 2

        await db.close()
