"""Permission Store — 权限规则与审批记录的 SQLite 持久化。

表结构：
- permission_rules: 权限规则
- approval_requests: 审批请求
- execution_claims: 执行声明
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.permission.models import (
    ApprovalRequest,
    ApprovalStatus,
    ExecutionClaim,
    PermissionResult,
    PermissionRule,
    PermissionRuleLayer,
    PermissionScope,
)

# ─── 建表 SQL ─────────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS permission_rules (
    id TEXT PRIMARY KEY,
    layer TEXT NOT NULL DEFAULT 'builtin_default',
    capability TEXT,
    tool_name TEXT,
    arguments_pattern TEXT,
    conditions TEXT NOT NULL DEFAULT '{}',
    policy TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    scope_type TEXT NOT NULL DEFAULT 'global',
    scope_id TEXT,
    expires_at TEXT,
    created_by TEXT,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_permission_rules_capability
    ON permission_rules(capability);
CREATE INDEX IF NOT EXISTS idx_permission_rules_tool_name
    ON permission_rules(tool_name);
CREATE INDEX IF NOT EXISTS idx_permission_rules_layer
    ON permission_rules(layer);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    tool_call_fingerprint TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_arguments TEXT NOT NULL DEFAULT '{}',
    capabilities TEXT NOT NULL DEFAULT '[]',
    trace TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    run_version INTEGER NOT NULL DEFAULT 0,
    execution_revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    resolved_at TEXT,
    consumed_at TEXT,
    resolved_by TEXT,
    approval_scope TEXT,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_run_id
    ON approval_requests(run_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_status
    ON approval_requests(status);

CREATE TABLE IF NOT EXISTS execution_claims (
    id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    tool_call_fingerprint TEXT NOT NULL,
    frozen_arguments TEXT NOT NULL DEFAULT '{}',
    frozen_capabilities TEXT NOT NULL DEFAULT '[]',
    run_version INTEGER NOT NULL DEFAULT 0,
    execution_revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    consumed_at TEXT,
    FOREIGN KEY (approval_id) REFERENCES approval_requests(id)
);

CREATE INDEX IF NOT EXISTS idx_execution_claims_approval_id
    ON execution_claims(approval_id);
CREATE INDEX IF NOT EXISTS idx_execution_claims_run_id
    ON execution_claims(run_id);
"""

# ─── 辅助 ─────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_to_dt(iso: str | None) -> datetime | None:
    if iso is None:
        return None
    return datetime.fromisoformat(iso)


# ─── SQLitePermissionStore ────────────────────────────────


class SQLitePermissionStore:
    """权限规则的 SQLite 持久化。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self, rule_id: str) -> PermissionRule | None:
        cursor = await self._db.execute(
            "SELECT * FROM permission_rules WHERE id = ?", (rule_id,)
        )
        row = await cursor.fetchone()
        return _row_to_rule(row) if row else None

    async def list_all(self) -> list[PermissionRule]:
        cursor = await self._db.execute(
            "SELECT * FROM permission_rules ORDER BY layer, priority DESC, id"
        )
        rows = await cursor.fetchall()
        return [_row_to_rule(r) for r in rows]

    async def list_by_capability(self, capability: str) -> list[PermissionRule]:
        cursor = await self._db.execute(
            "SELECT * FROM permission_rules WHERE capability = ? ORDER BY layer, priority DESC",
            (capability,),
        )
        rows = await cursor.fetchall()
        return [_row_to_rule(r) for r in rows]

    async def list_by_tool(self, tool_name: str) -> list[PermissionRule]:
        cursor = await self._db.execute(
            "SELECT * FROM permission_rules WHERE tool_name = ? ORDER BY layer, priority DESC",
            (tool_name,),
        )
        rows = await cursor.fetchall()
        return [_row_to_rule(r) for r in rows]

    async def create(self, rule: PermissionRule) -> PermissionRule:
        now = _now_iso()
        await self._db.execute(
            """INSERT INTO permission_rules
            (id, layer, capability, tool_name, arguments_pattern, conditions,
             policy, priority, scope_type, scope_id, expires_at, created_by,
             description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.rule_id, rule.layer.value,
                rule.capability, rule.tool_name, rule.arguments_pattern,
                json.dumps(rule.conditions), rule.policy.value,
                rule.priority, rule.scope_type.value, rule.scope_id,
                _iso_to_dt(rule.expires_at) and rule.expires_at.isoformat(),
                rule.created_by, rule.description, now, now,
            ),
        )
        await self._db.commit()
        rule.created_at = datetime.fromisoformat(now)
        rule.updated_at = datetime.fromisoformat(now)
        return rule

    async def update(self, rule_id: str, **fields: Any) -> PermissionRule:
        existing = await self.get(rule_id)
        if existing is None:
            raise KeyError(f"规则不存在: {rule_id}")

        updates: list[str] = []
        params: list[Any] = []

        for key, value in fields.items():
            if key == "policy" and isinstance(value, str):
                updates.append("policy = ?")
                params.append(value)
            elif key == "priority":
                updates.append("priority = ?")
                params.append(value)
            elif key == "conditions":
                updates.append("conditions = ?")
                params.append(json.dumps(value))
            elif key == "description":
                updates.append("description = ?")
                params.append(value)

        if not updates:
            return existing

        updates.append("updated_at = ?")
        params.append(_now_iso())
        params.append(rule_id)

        await self._db.execute(
            f"UPDATE permission_rules SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return await self.get(rule_id)  # type: ignore

    async def delete(self, rule_id: str) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM permission_rules WHERE id = ?", (rule_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_by_scope(self, scope_type: str, scope_id: str) -> int:
        cursor = await self._db.execute(
            "DELETE FROM permission_rules WHERE scope_type = ? AND scope_id = ?",
            (scope_type, scope_id),
        )
        await self._db.commit()
        return cursor.rowcount

    async def reset_to_defaults(self, default_rules: list[PermissionRule]) -> list[PermissionRule]:
        """删除所有非系统规则，重新插入默认规则。"""
        await self._db.execute(
            "DELETE FROM permission_rules WHERE layer != ?",
            (PermissionRuleLayer.SYSTEM_GUARDRAIL.value,),
        )
        for rule in default_rules:
            await self.create(rule)
        await self._db.commit()
        return await self.list_all()


# ─── SQLiteApprovalStore ──────────────────────────────────


class SQLiteApprovalStore:
    """审批请求的 SQLite 持久化。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        now = _now_iso()
        await self._db.execute(
            """INSERT INTO approval_requests
            (id, run_id, session_id, tool_call_id, tool_call_fingerprint,
             tool_name, tool_arguments, capabilities, trace,
             status, run_version, execution_revision,
             created_at, expires_at, resolved_at, consumed_at,
             resolved_by, approval_scope, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                approval.approval_id, approval.run_id, approval.session_id,
                approval.tool_call_id, approval.tool_call_fingerprint,
                approval.tool_name, json.dumps(approval.tool_arguments),
                json.dumps(_capabilities_to_dicts(approval.capabilities)),
                json.dumps(_trace_to_dict(approval.trace)),
                approval.status.value, approval.run_version, approval.execution_revision,
                now,
                approval.expires_at.isoformat() if approval.expires_at else None,
                None, None,
                None, None, None,
            ),
        )
        await self._db.commit()
        approval.created_at = datetime.fromisoformat(now)
        return approval

    async def get(self, approval_id: str) -> ApprovalRequest | None:
        cursor = await self._db.execute(
            "SELECT * FROM approval_requests WHERE id = ?", (approval_id,)
        )
        row = await cursor.fetchone()
        return _row_to_approval(row) if row else None

    async def list_pending(self, run_id: str | None = None) -> list[ApprovalRequest]:
        if run_id:
            cursor = await self._db.execute(
                "SELECT * FROM approval_requests WHERE run_id = ? AND status = 'pending' ORDER BY created_at",
                (run_id,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM approval_requests WHERE status = 'pending' ORDER BY created_at"
            )
        rows = await cursor.fetchall()
        return [_row_to_approval(r) for r in rows]

    async def resolve(
        self,
        approval_id: str,
        status: ApprovalStatus,
        resolved_by: str,
        approval_scope: PermissionScope | None = None,
        reason: str | None = None,
    ) -> ApprovalRequest:
        now = _now_iso()
        await self._db.execute(
            """UPDATE approval_requests
            SET status = ?, resolved_at = ?, resolved_by = ?, approval_scope = ?, reason = ?
            WHERE id = ? AND status = 'pending'""",
            (status.value, now, resolved_by,
             approval_scope.value if approval_scope else None,
             reason, approval_id),
        )
        await self._db.commit()
        return await self.get(approval_id)  # type: ignore

    async def consume(self, approval_id: str) -> ApprovalRequest:
        now = _now_iso()
        await self._db.execute(
            """UPDATE approval_requests
            SET status = 'consumed', consumed_at = ?
            WHERE id = ? AND status = 'approved'""",
            (now, approval_id),
        )
        await self._db.commit()
        return await self.get(approval_id)  # type: ignore

    async def expire_stale(self, before: datetime) -> int:
        cursor = await self._db.execute(
            """UPDATE approval_requests
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < ?""",
            (before.isoformat(),),
        )
        await self._db.commit()
        return cursor.rowcount


# ─── SQLiteClaimStore ─────────────────────────────────────


class SQLiteClaimStore:
    """执行声明的 SQLite 持久化。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def create(self, claim: ExecutionClaim) -> ExecutionClaim:
        now = _now_iso()
        await self._db.execute(
            """INSERT INTO execution_claims
            (id, approval_id, run_id, tool_call_id, tool_call_fingerprint,
             frozen_arguments, frozen_capabilities, run_version, execution_revision,
             created_at, expires_at, consumed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                claim.claim_id, claim.approval_id, claim.run_id,
                claim.tool_call_id, claim.tool_call_fingerprint,
                json.dumps(claim.frozen_arguments),
                json.dumps(_capabilities_to_dicts(claim.frozen_capabilities)),
                claim.run_version, claim.execution_revision,
                now,
                claim.expires_at.isoformat() if claim.expires_at else None,
                None,
            ),
        )
        await self._db.commit()
        claim.created_at = datetime.fromisoformat(now)
        return claim

    async def get(self, claim_id: str) -> ExecutionClaim | None:
        cursor = await self._db.execute(
            "SELECT * FROM execution_claims WHERE id = ?", (claim_id,)
        )
        row = await cursor.fetchone()
        return _row_to_claim(row) if row else None

    async def get_by_approval(self, approval_id: str) -> ExecutionClaim | None:
        cursor = await self._db.execute(
            "SELECT * FROM execution_claims WHERE approval_id = ?", (approval_id,)
        )
        row = await cursor.fetchone()
        return _row_to_claim(row) if row else None

    async def consume(self, claim_id: str) -> ExecutionClaim:
        now = _now_iso()
        await self._db.execute(
            "UPDATE execution_claims SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
            (now, claim_id),
        )
        await self._db.commit()
        return await self.get(claim_id)  # type: ignore


# ─── 行转模型 ─────────────────────────────────────────────


def _row_to_rule(row: aiosqlite.Row) -> PermissionRule:
    return PermissionRule(
        rule_id=row["id"],
        layer=PermissionRuleLayer(row["layer"]),
        capability=row["capability"],
        tool_name=row["tool_name"],
        arguments_pattern=row["arguments_pattern"],
        conditions=json.loads(row["conditions"]),
        policy=PermissionResult(row["policy"]),
        priority=row["priority"],
        scope_type=PermissionScope(row["scope_type"]),
        scope_id=row["scope_id"],
        expires_at=_iso_to_dt(row["expires_at"]),
        created_by=row["created_by"],
        description=row["description"],
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_iso_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
    )


def _row_to_approval(row: aiosqlite.Row) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=row["id"],
        run_id=row["run_id"],
        session_id=row["session_id"],
        tool_call_id=row["tool_call_id"],
        tool_call_fingerprint=row["tool_call_fingerprint"],
        tool_name=row["tool_name"],
        tool_arguments=json.loads(row["tool_arguments"]),
        capabilities=_dicts_to_capabilities(json.loads(row["capabilities"])),
        trace=_dict_to_trace(json.loads(row["trace"])),
        status=ApprovalStatus(row["status"]),
        run_version=row["run_version"],
        execution_revision=row["execution_revision"],
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        expires_at=_iso_to_dt(row["expires_at"]),
        resolved_at=_iso_to_dt(row["resolved_at"]),
        consumed_at=_iso_to_dt(row["consumed_at"]),
        resolved_by=row["resolved_by"],
        approval_scope=PermissionScope(row["approval_scope"]) if row["approval_scope"] else None,
        reason=row["reason"],
    )


def _row_to_claim(row: aiosqlite.Row) -> ExecutionClaim:
    return ExecutionClaim(
        claim_id=row["id"],
        approval_id=row["approval_id"],
        run_id=row["run_id"],
        tool_call_id=row["tool_call_id"],
        tool_call_fingerprint=row["tool_call_fingerprint"],
        frozen_arguments=json.loads(row["frozen_arguments"]),
        frozen_capabilities=_dicts_to_capabilities(json.loads(row["frozen_capabilities"])),
        run_version=row["run_version"],
        execution_revision=row["execution_revision"],
        created_at=_iso_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        expires_at=_iso_to_dt(row["expires_at"]),
        consumed_at=_iso_to_dt(row["consumed_at"]),
    )


# ─── 序列化辅助 ───────────────────────────────────────────


def _capabilities_to_dicts(caps: list[ResolvedCapability]) -> list[dict]:
    return [
        {
            "capability": c.capability,
            "metadata": c.metadata,
            "source_action_id": c.source_action_id,
            "completeness": c.completeness.value,
            "warnings": c.warnings,
        }
        for c in caps
    ]


def _dicts_to_capabilities(dicts: list[dict]) -> list[ResolvedCapability]:
    return [
        ResolvedCapability(
            capability=d["capability"],
            metadata=d.get("metadata", {}),
            source_action_id=d.get("source_action_id", ""),
            completeness=AnalysisCompleteness(d.get("completeness", "complete")),
            warnings=d.get("warnings", []),
        )
        for d in dicts
    ]


def _trace_to_dict(trace: Any) -> dict:
    return {
        "result": trace.result.value,
        "aggregated_reason": trace.aggregated_reason,
        "completeness": trace.completeness.value,
        "warnings": trace.warnings,
    }


def _dict_to_trace(d: dict) -> Any:
    from app.permission.models import PermissionTrace
    return PermissionTrace(
        result=PermissionResult(d.get("result", "require_approval")),
        capability_decisions=[],
        aggregated_reason=d.get("aggregated_reason", ""),
        completeness=AnalysisCompleteness(d.get("completeness", "complete")),
        warnings=d.get("warnings", []),
    )


# ─── 初始化 ───────────────────────────────────────────────


async def init_permission_db(db: aiosqlite.Connection) -> None:
    """在已有数据库连接上初始化 Permission 表。"""
    await db.executescript(_CREATE_TABLES)
    await db.commit()
