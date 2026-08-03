"""Permission HTTP API — 权限规则管理。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.permission.models import (
    CreatePermissionRequest,
    PermissionListResponse,
    PermissionRule,
    PermissionRuleLayer,
    PermissionRuleResponse,
    PermissionResult,
    PermissionScope,
    UpdatePermissionRequest,
    new_rule_id,
)
from app.permission.store import SQLitePermissionStore
from datetime import datetime, timezone

router = APIRouter(prefix="/api/permissions", tags=["permissions"])

_store: SQLitePermissionStore | None = None
_default_rules: list[PermissionRule] = []


def init_permission_api(
    store: SQLitePermissionStore,
    default_rules: list[PermissionRule],
) -> None:
    global _store, _default_rules
    _store = store
    _default_rules = default_rules


def _get_store() -> SQLitePermissionStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="Permission 模块未初始化")
    return _store


@router.get("", response_model=PermissionListResponse)
async def list_rules(
    capability: str | None = None,
    tool_name: str | None = None,
) -> PermissionListResponse:
    store = _get_store()
    if capability:
        rules = await store.list_by_capability(capability)
    elif tool_name:
        rules = await store.list_by_tool(tool_name)
    else:
        rules = await store.list_all()
    return PermissionListResponse(
        rules=[_to_response(r) for r in rules],
        total=len(rules),
    )


@router.post("", response_model=PermissionRuleResponse, status_code=201)
async def create_rule(request: CreatePermissionRequest) -> PermissionRuleResponse:
    store = _get_store()
    now = datetime.now(timezone.utc)
    rule = PermissionRule(
        rule_id=new_rule_id(),
        layer=PermissionRuleLayer.USER_GLOBAL_RULE,
        capability=request.capability,
        tool_name=request.tool_name,
        arguments_pattern=request.arguments_pattern,
        conditions=request.conditions,
        policy=PermissionResult(request.policy),
        priority=request.priority,
        scope_type=PermissionScope(request.scope_type),
        scope_id=request.scope_id,
        expires_at=None,
        created_by="user",
        description=request.description,
        created_at=now,
        updated_at=now,
    )
    created = await store.create(rule)
    return _to_response(created)


@router.patch("/{rule_id}", response_model=PermissionRuleResponse)
async def update_rule(
    rule_id: str,
    request: UpdatePermissionRequest,
) -> PermissionRuleResponse:
    store = _get_store()
    fields = {}
    if request.policy is not None:
        fields["policy"] = request.policy
    if request.priority is not None:
        fields["priority"] = request.priority
    if request.conditions is not None:
        fields["conditions"] = request.conditions
    if request.description is not None:
        fields["description"] = request.description
    try:
        updated = await store.update(rule_id, **fields)
        return _to_response(updated)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"规则不存在: {rule_id}")


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: str) -> None:
    store = _get_store()
    deleted = await store.delete(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"规则不存在: {rule_id}")


@router.post("/reset", response_model=PermissionListResponse)
async def reset_rules() -> PermissionListResponse:
    store = _get_store()
    rules = await store.reset_to_defaults(_default_rules)
    return PermissionListResponse(
        rules=[_to_response(r) for r in rules],
        total=len(rules),
    )


def _to_response(rule: PermissionRule) -> PermissionRuleResponse:
    return PermissionRuleResponse(
        rule_id=rule.rule_id,
        layer=rule.layer.value,
        capability=rule.capability,
        tool_name=rule.tool_name,
        arguments_pattern=rule.arguments_pattern,
        conditions=rule.conditions,
        policy=rule.policy.value,
        priority=rule.priority,
        scope_type=rule.scope_type.value,
        scope_id=rule.scope_id,
        expires_at=rule.expires_at,
        created_by=rule.created_by,
        description=rule.description,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )
