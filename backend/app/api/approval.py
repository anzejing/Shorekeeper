"""Approval HTTP API — 审批管理。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.permission.approval import ApprovalManager
from app.permission.models import (
    ApprovalListResponse,
    ApprovalRequestResponse,
    ApprovalStatus,
    PermissionScope,
    ResolveApprovalRequest,
)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

_manager: ApprovalManager | None = None


def init_approval_api(manager: ApprovalManager) -> None:
    global _manager
    _manager = manager


def _get_manager() -> ApprovalManager:
    if _manager is None:
        raise HTTPException(status_code=503, detail="Approval 模块未初始化")
    return _manager


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    run_id: str | None = None,
    status: str | None = None,
) -> ApprovalListResponse:
    manager = _get_manager()
    if status == "pending":
        approvals = await manager.list_pending(run_id)
    else:
        approvals = await manager.list_pending(run_id)
    return ApprovalListResponse(
        approvals=[_to_response(a) for a in approvals],
        total=len(approvals),
    )


@router.get("/{approval_id}", response_model=ApprovalRequestResponse)
async def get_approval(approval_id: str) -> ApprovalRequestResponse:
    manager = _get_manager()
    approval = await manager.get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail=f"审批不存在: {approval_id}")
    return _to_response(approval)


@router.post("/{approval_id}", response_model=ApprovalRequestResponse)
async def resolve_approval(
    approval_id: str,
    request: ResolveApprovalRequest,
) -> ApprovalRequestResponse:
    manager = _get_manager()
    approval = await manager.get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail=f"审批不存在: {approval_id}")
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"审批状态不是 PENDING: {approval.status}")

    if request.approved:
        scope = PermissionScope(request.scope)
        result = await manager.approve(
            approval_id, resolved_by="user", scope=scope, reason=request.reason
        )
    else:
        result = await manager.deny(
            approval_id, resolved_by="user", reason=request.reason
        )

    return _to_response(result)


def _to_response(a) -> ApprovalRequestResponse:
    return ApprovalRequestResponse(
        approval_id=a.approval_id,
        run_id=a.run_id,
        tool_call_id=a.tool_call_id,
        tool_name=a.tool_name,
        tool_arguments=a.tool_arguments,
        status=a.status.value,
        created_at=a.created_at,
        expires_at=a.expires_at,
        resolved_at=a.resolved_at,
        reason=a.reason,
    )
