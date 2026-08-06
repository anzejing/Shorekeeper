"""审批管理测试——过期清理与状态流转。"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from app.permission.approval import ApprovalManager
from app.permission.models import (
    AnalysisCompleteness,
    ApprovalStatus,
    CapabilityDecision,
    PermissionResult,
    PermissionTrace,
)
from app.permission.store import (
    SQLiteApprovalStore,
    SQLiteClaimStore,
    init_permission_db,
)
from app.runtime.models import ToolCall


async def _make_approval_env() -> tuple[ApprovalManager, aiosqlite.Connection, str]:
    """创建审批测试环境。"""
    db_path = os.path.join(
        tempfile.mkdtemp(), f"test_approval_{os.getpid()}.db"
    )
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await init_permission_db(db)
    approval_store = SQLiteApprovalStore(db)
    claim_store = SQLiteClaimStore(db)
    manager = ApprovalManager(approval_store, claim_store, default_ttl_seconds=3600)
    return manager, db, db_path


def _make_trace() -> PermissionTrace:
    """构造最小权限追踪。"""
    return PermissionTrace(
        result=PermissionResult.REQUIRE_APPROVAL,
        capability_decisions=[
            CapabilityDecision(
                capability="system.execute_unknown",
                result=PermissionResult.REQUIRE_APPROVAL,
                matched_rule=None,
                reason="测试",
            )
        ],
        aggregated_reason="测试规则",
        completeness=AnalysisCompleteness.COMPLETE,
        warnings=[],
    )


async def _create_approval(
    manager: ApprovalManager,
    *,
    run_id: str = "run-1",
    tool_name: str = "bash_execute",
    command: str = "echo hello",
    ttl_seconds: int | None = 3600,
) -> str:
    """创建一条审批请求。"""
    approval = await manager.create(
        run_id=run_id,
        session_id="sess-1",
        tool_call=ToolCall(
            tool_call_id="call-test-1",
            tool_name=tool_name,
            arguments={"command": command},
        ),
        capabilities=[],
        trace=_make_trace(),
        run_version=0,
        execution_revision=0,
        workspace_id="",
    )
    return approval.approval_id


class TestExpireStale:
    @pytest.mark.asyncio
    async def test_expire_stale_marks_expired(self) -> None:
        manager, db, path = await _make_approval_env()
        approval_id = await _create_approval(manager, ttl_seconds=3600)

        # 手动把 expires_at 改为过去（模拟 TTL 过期）
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        await db.execute(
            "UPDATE approval_requests SET expires_at = ? WHERE id = ?",
            (past.isoformat(), approval_id),
        )
        await db.commit()

        # 过期清理
        count = await manager.expire_stale()
        assert count == 1

        approval = await manager.get(approval_id)
        assert approval is not None
        assert approval.status == ApprovalStatus.EXPIRED

        await db.close()
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_expire_stale_skips_active(self) -> None:
        manager, db, path = await _make_approval_env()
        await _create_approval(manager, ttl_seconds=3600)  # 未过期

        count = await manager.expire_stale()
        assert count == 0

        await db.close()
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_expire_stale_skips_resolved(self) -> None:
        manager, db, path = await _make_approval_env()
        approval_id = await _create_approval(manager, ttl_seconds=3600)

        await manager.approve(approval_id, resolved_by="user", scope=None)

        # 手动把 expires_at 改为过去
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        await db.execute(
            "UPDATE approval_requests SET expires_at = ? WHERE id = ?",
            (past.isoformat(), approval_id),
        )
        await db.commit()

        # 已 resolved 的审批不应被标记 expired
        count = await manager.expire_stale()
        assert count == 0

        approval = await manager.get(approval_id)
        assert approval.status == ApprovalStatus.APPROVED

        await db.close()
        os.unlink(path)


class TestFindResolvedByTool:
    @pytest.mark.asyncio
    async def test_find_approved_by_tool_within_run(self) -> None:
        manager, db, path = await _make_approval_env()
        approval_id = await _create_approval(manager, run_id="run-1")

        await manager.approve(approval_id, resolved_by="user", scope=None)

        found = await manager.find_resolved_by_tool(
            run_id="run-1",
            tool_name="bash_execute",
            tool_arguments={"command": "echo hello"},
        )
        assert found is not None
        assert found.status == ApprovalStatus.APPROVED

        await db.close()
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_find_denied_by_tool_within_run(self) -> None:
        manager, db, path = await _make_approval_env()
        approval_id = await _create_approval(manager, run_id="run-1")

        await manager.deny(approval_id, resolved_by="user")

        found = await manager.find_resolved_by_tool(
            run_id="run-1",
            tool_name="bash_execute",
            tool_arguments={"command": "echo hello"},
        )
        assert found is not None
        assert found.status == ApprovalStatus.DENIED

        await db.close()
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_does_not_match_other_run(self) -> None:
        manager, db, path = await _make_approval_env()
        approval_id = await _create_approval(manager, run_id="run-1")

        await manager.approve(approval_id, resolved_by="user", scope=None)

        # 其他 run 不应匹配到 run-1 的审批
        found = await manager.find_resolved_by_tool(
            run_id="run-2",
            tool_name="bash_execute",
            tool_arguments={"command": "echo hello"},
        )
        assert found is None

        await db.close()
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_skips_expired_approval(self) -> None:
        manager, db, path = await _make_approval_env()
        approval_id = await _create_approval(manager, run_id="run-1")

        await manager.approve(approval_id, resolved_by="user", scope=None)

        # 手动把 expires_at 改为过去
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        await db.execute(
            "UPDATE approval_requests SET expires_at = ? WHERE id = ?",
            (past.isoformat(), approval_id),
        )
        await db.commit()

        # 过期审批不应再参与自动放行
        found = await manager.find_resolved_by_tool(
            run_id="run-1",
            tool_name="bash_execute",
            tool_arguments={"command": "echo hello"},
        )
        assert found is None

        await db.close()
        os.unlink(path)
