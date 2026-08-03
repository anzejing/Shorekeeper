"""ApprovalManager — 审批生命周期管理。

职责：
- 创建审批记录
- 查询审批
- 审批状态流转（PENDING → APPROVED/DENIED → CONSUMED）
- 过期处理
- 原子执行声明（ExecutionClaim）

不负责：
- 阻塞等待
- Runtime Suspend/Resume
- HTTP 通信
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.permission.fingerprint import compute_fingerprint
from app.permission.models import (
    ApprovalRequest,
    ApprovalStatus,
    ExecutionClaim,
    PermissionDecision,
    PermissionScope,
    PermissionTrace,
    ResolvedCapability,
    new_approval_id,
    new_action_id,
)
from app.permission.store import SQLiteApprovalStore, SQLiteClaimStore
from app.runtime.models import ToolCall

log = logging.getLogger(__name__)


class ApprovalManager:
    """审批管理器。"""

    def __init__(
        self,
        approval_store: SQLiteApprovalStore,
        claim_store: SQLiteClaimStore,
        default_ttl_seconds: int = 3600,
    ) -> None:
        self._approval_store = approval_store
        self._claim_store = claim_store
        self._default_ttl = default_ttl_seconds

    async def create(
        self,
        run_id: str,
        session_id: str,
        tool_call: ToolCall,
        capabilities: list[ResolvedCapability],
        trace: PermissionTrace,
        run_version: int,
        execution_revision: int,
        workspace_id: str = "",
    ) -> ApprovalRequest:
        """创建审批请求。"""
        # 计算 fingerprint（包含 capability metadata）
        fp = compute_fingerprint(
            tool_name=tool_call.tool_name,
            canonical_arguments=tool_call.arguments,
            capabilities=capabilities,
            workspace_id=workspace_id,
            run_id=run_id,
            session_id=session_id,
        )

        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(
            now.timestamp() + self._default_ttl, tz=timezone.utc
        )

        approval = ApprovalRequest(
            approval_id=new_approval_id(),
            run_id=run_id,
            session_id=session_id,
            tool_call_id=tool_call.tool_call_id,
            tool_call_fingerprint=fp,
            tool_name=tool_call.tool_name,
            tool_arguments=tool_call.arguments,
            capabilities=capabilities,
            trace=trace,
            status=ApprovalStatus.PENDING,
            run_version=run_version,
            execution_revision=execution_revision,
            created_at=now,
            expires_at=expires_at,
            resolved_at=None,
            consumed_at=None,
            resolved_by=None,
            approval_scope=None,
            reason=None,
        )

        return await self._approval_store.create(approval)

    async def get(self, approval_id: str) -> ApprovalRequest | None:
        """获取审批请求。"""
        return await self._approval_store.get(approval_id)

    async def list_pending(self, run_id: str | None = None) -> list[ApprovalRequest]:
        """列出待审批请求。"""
        return await self._approval_store.list_pending(run_id)

    async def approve(
        self,
        approval_id: str,
        resolved_by: str,
        scope: PermissionScope = PermissionScope.SESSION,
        reason: str | None = None,
    ) -> ApprovalRequest:
        """审批通过。"""
        return await self._approval_store.resolve(
            approval_id,
            ApprovalStatus.APPROVED,
            resolved_by,
            scope,
            reason,
        )

    async def deny(
        self,
        approval_id: str,
        resolved_by: str,
        reason: str | None = None,
    ) -> ApprovalRequest:
        """审批拒绝。"""
        return await self._approval_store.resolve(
            approval_id,
            ApprovalStatus.DENIED,
            resolved_by,
            reason=reason,
        )

    async def create_claim(
        self,
        approval: ApprovalRequest,
    ) -> ExecutionClaim:
        """创建原子执行声明。

        审批通过后，Runtime 调用此方法创建执行声明。
        声明绑定冻结的参数，确保执行时参数不变。
        """
        claim = ExecutionClaim(
            claim_id=new_action_id(),
            approval_id=approval.approval_id,
            run_id=approval.run_id,
            tool_call_id=approval.tool_call_id,
            tool_call_fingerprint=approval.tool_call_fingerprint,
            frozen_arguments=approval.tool_arguments,
            frozen_capabilities=approval.capabilities,
            run_version=approval.run_version,
            execution_revision=approval.execution_revision,
            created_at=datetime.now(timezone.utc),
            expires_at=approval.expires_at,
            consumed_at=None,
        )
        return await self._claim_store.create(claim)

    async def consume_claim(self, claim_id: str) -> ExecutionClaim:
        """消费执行声明。幂等。"""
        return await self._claim_store.consume(claim_id)

    async def get_claim(self, claim_id: str) -> ExecutionClaim | None:
        """获取执行声明。"""
        return await self._claim_store.get(claim_id)

    async def get_claim_by_approval(self, approval_id: str) -> ExecutionClaim | None:
        """按审批 ID 获取执行声明。"""
        return await self._claim_store.get_by_approval(approval_id)

    async def expire_stale(self) -> int:
        """过期处理——标记过期的审批请求。"""
        now = datetime.now(timezone.utc)
        return await self._approval_store.expire_stale(now)
