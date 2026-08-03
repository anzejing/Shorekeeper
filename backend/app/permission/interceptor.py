"""PermissionInterceptor — 桥接 PermissionEngine + ApprovalManager → ToolDecision。

实现 InterceptorChain Protocol，注入到 Runtime。

流程：
1. PermissionEngine.evaluate() → PermissionDecision
2. ALLOW → Allow()
3. DENY → Reject(reason)
4. REQUIRE_APPROVAL → 创建审批 → SuspendDecision(approval_id)
"""

from __future__ import annotations

import logging
from typing import Any

from app.permission.approval import ApprovalManager
from app.permission.engine import PermissionEngine
from app.permission.models import (
    PermissionDecision,
    PermissionResult,
    ResolvedCapability,
)
from app.runtime.models import (
    Allow,
    Reject,
    SuspendDecision,
    SuspendRequest,
    SuspensionType,
    ToolCall,
    ToolDecision,
)

log = logging.getLogger(__name__)


class PermissionInterceptor:
    """权限拦截器——实现 InterceptorChain Protocol。"""

    def __init__(
        self,
        engine: PermissionEngine,
        approval_manager: ApprovalManager,
        run_id: str = "",
        session_id: str = "",
        run_version: int = 0,
        execution_revision: int = 0,
        workspace_id: str = "",
    ) -> None:
        self._engine = engine
        self._approval_manager = approval_manager
        self._run_id = run_id
        self._session_id = session_id
        self._run_version = run_version
        self._execution_revision = execution_revision
        self._workspace_id = workspace_id

    def update_run_context(
        self,
        run_id: str,
        session_id: str,
        run_version: int,
        execution_revision: int,
    ) -> None:
        """更新 Run 上下文（每次 resume 后调用）。"""
        self._run_id = run_id
        self._session_id = session_id
        self._run_version = run_version
        self._execution_revision = execution_revision

    async def process(self, tool_call: ToolCall) -> ToolDecision:
        """处理工具调用的权限检查。"""
        # 1. 评估权限
        decision = await self._engine.evaluate(tool_call)

        # 2. ALLOW → 直接通过
        if decision.result == PermissionResult.ALLOW:
            log.info("权限通过: %s — %s", tool_call.tool_name, decision.trace.aggregated_reason)
            return Allow()

        # 3. DENY → 拒绝
        if decision.result == PermissionResult.DENY:
            log.warning("权限拒绝: %s — %s", tool_call.tool_name, decision.trace.aggregated_reason)
            return Reject(reason=decision.trace.aggregated_reason)

        # 4. REQUIRE_APPROVAL → 创建审批 → 暂停
        if decision.result == PermissionResult.REQUIRE_APPROVAL:
            approval = await self._approval_manager.create(
                run_id=self._run_id,
                session_id=self._session_id,
                tool_call=tool_call,
                capabilities=self._extract_capabilities(decision),
                trace=decision.trace,
                run_version=self._run_version,
                execution_revision=self._execution_revision,
                workspace_id=self._workspace_id,
            )
            log.info(
                "需要审批: %s — approval_id=%s",
                tool_call.tool_name,
                approval.approval_id,
            )
            return SuspendDecision(
                request=SuspendRequest(
                    suspension_type=SuspensionType.TOOL_APPROVAL,
                    tool_call=tool_call,
                    reason=decision.trace.aggregated_reason,
                    metadata={"approval_id": approval.approval_id},
                )
            )

        # 不应到达
        return Reject(reason="未知权限决策")

    def _extract_capabilities(self, decision: PermissionDecision) -> list[ResolvedCapability]:
        """从决策中提取 capabilities。"""
        caps: list[ResolvedCapability] = []
        for cd in decision.trace.capability_decisions:
            if cd.matched_rule:
                caps.append(ResolvedCapability(
                    capability=cd.capability,
                    metadata={},
                    source_action_id="",
                    completeness=decision.trace.completeness,
                    warnings=[],
                ))
        return caps
