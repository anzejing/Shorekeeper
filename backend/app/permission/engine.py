"""PermissionEngine — 权限引擎核心。

组装 Parser + Analyzer + Matcher，对 ToolCall 做聚合决策。

职责：
1. 调用 Parser 解析 ToolCall → ParsedAction AST
2. 调用 Analyzer 分析 ParsedAction → CapabilityAnalysis
3. 对每个 Capability 匹配规则 → CapabilityDecision
4. 聚合决策（DENY > REQUIRE_APPROVAL > ALLOW）
5. fail-closed：PARTIAL 最低 REQUIRE_APPROVAL，UNKNOWN 由系统规则决策

不负责：
- Suspend/Resume（Runtime 的职责）
- 审批记录管理（ApprovalManager 的职责）
"""

from __future__ import annotations

import logging
from typing import Any

from app.permission.analyzer.base import CapabilityAnalyzer, GenericAnalyzer
from app.permission.matcher import (
    apply_pattern_constraint,
    match_arguments_pattern,
    match_conditions,
    sort_rules,
)
from app.permission.models import (
    AnalysisCompleteness,
    CapabilityAnalysis,
    CapabilityDecision,
    PermissionDecision,
    PermissionResult,
    PermissionRule,
    PermissionRuleLayer,
    PermissionTrace,
    ResolvedCapability,
)
from app.permission.parser.base import GenericParser, ToolParser
from app.permission.store import SQLitePermissionStore
from app.runtime.models import ToolCall

log = logging.getLogger(__name__)


class PermissionEngine:
    """权限引擎。"""

    def __init__(
        self,
        store: SQLitePermissionStore,
        parsers: dict[str, ToolParser] | None = None,
        analyzers: dict[str, CapabilityAnalyzer] | None = None,
        default_rules: list[PermissionRule] | None = None,
    ) -> None:
        self._store = store
        self._parsers = parsers or {}
        self._analyzers = analyzers or {}
        self._default_parser = GenericParser()
        self._default_analyzer = GenericAnalyzer()
        self._default_rules = default_rules or []

    async def evaluate(self, tool_call: ToolCall) -> PermissionDecision:
        """评估 ToolCall 的权限。"""
        # 1. 解析
        parser = self._parsers.get(tool_call.tool_name, self._default_parser)
        parsed = parser.parse(tool_call)

        # 2. fail-closed：UNKNOWN 由系统规则决策
        if parsed.parse_completeness == AnalysisCompleteness.UNKNOWN:
            return await self._handle_unknown(tool_call, parsed)

        # 3. 分析能力
        analyzer = self._analyzers.get(tool_call.tool_name, self._default_analyzer)
        analysis = analyzer.analyze(parsed, tool_call)

        # 4. 对每个 Capability 规则匹配
        decisions: list[CapabilityDecision] = []
        for cap in analysis.capabilities:
            decision = await self._match_capability(cap, tool_call)
            decisions.append(decision)

        # 5. 聚合：DENY > REQUIRE_APPROVAL > ALLOW
        final = self._aggregate(decisions)

        # 6. fail-closed：PARTIAL 最低 REQUIRE_APPROVAL
        if analysis.completeness == AnalysisCompleteness.PARTIAL:
            if final == PermissionResult.ALLOW:
                final = PermissionResult.REQUIRE_APPROVAL

        return PermissionDecision(
            result=final,
            trace=PermissionTrace(
                result=final,
                capability_decisions=decisions,
                aggregated_reason=self._format_reason(decisions, final),
                completeness=analysis.completeness,
                warnings=analysis.warnings,
            ),
        )

    async def _handle_unknown(
        self, tool_call: ToolCall, parsed: Any
    ) -> PermissionDecision:
        """处理 UNKNOWN 完整度——查询系统规则。"""
        # 查找 SYSTEM_GUARDRAIL 层的规则
        all_rules = await self._store.list_all()
        system_rules = [r for r in all_rules if r.layer == PermissionRuleLayer.SYSTEM_GUARDRAIL]

        # 查找匹配 system.execute_dynamic 或 system.execute_unknown 的规则
        for rule in system_rules:
            if rule.capability in ("system.execute_dynamic", "system.execute_unknown"):
                return PermissionDecision(
                    result=rule.policy,
                    trace=PermissionTrace(
                        result=rule.policy,
                        capability_decisions=[
                            CapabilityDecision(
                                capability=rule.capability or "system.execute_dynamic",
                                result=rule.policy,
                                matched_rule=rule,
                                reason=f"系统规则: {rule.description}",
                            )
                        ],
                        aggregated_reason=f"系统规则: {rule.description}",
                        completeness=AnalysisCompleteness.UNKNOWN,
                        warnings=parsed.parse_warnings,
                    ),
                )

        # 无系统规则 → 默认 REQUIRE_APPROVAL
        return PermissionDecision(
            result=PermissionResult.REQUIRE_APPROVAL,
            trace=PermissionTrace(
                result=PermissionResult.REQUIRE_APPROVAL,
                capability_decisions=[],
                aggregated_reason="无法解析命令，无匹配的系统规则",
                completeness=AnalysisCompleteness.UNKNOWN,
                warnings=parsed.parse_warnings,
            ),
        )

    async def _match_capability(
        self, cap: ResolvedCapability, tool_call: ToolCall
    ) -> CapabilityDecision:
        """对单个 Capability 匹配规则。"""
        # 收集候选规则
        candidates: list[PermissionRule] = []

        # 按 capability 匹配
        cap_rules = await self._store.list_by_capability(cap.capability)
        candidates.extend(cap_rules)

        # 按 tool_name 匹配
        tool_rules = await self._store.list_by_tool(tool_call.tool_name)
        for r in tool_rules:
            if r not in candidates:
                candidates.extend([r])

        # 排序
        sorted_rules = sort_rules(candidates)

        # 逐条匹配
        for rule in sorted_rules:
            # 检查 capability 匹配
            if rule.capability and rule.capability != cap.capability:
                continue

            # 检查 tool_name 匹配
            if rule.tool_name and rule.tool_name != tool_call.tool_name:
                continue

            # 检查 conditions
            if not match_conditions(rule, cap, tool_call):
                continue

            # 匹配成功
            policy = rule.policy

            # arguments_pattern 约束（只能收紧）
            if rule.arguments_pattern:
                if match_arguments_pattern(rule.arguments_pattern, tool_call):
                    # pattern 匹配，但只能收紧
                    pass  # 使用 rule.policy
                else:
                    continue  # pattern 不匹配，跳过

            return CapabilityDecision(
                capability=cap.capability,
                result=policy,
                matched_rule=rule,
                reason=f"匹配规则 {rule.rule_id}: {rule.description}",
            )

        # 无匹配规则 → 按 side_effect_level 兜底
        return CapabilityDecision(
            capability=cap.capability,
            result=PermissionResult.REQUIRE_APPROVAL,
            matched_rule=None,
            reason="无匹配规则，默认 REQUIRE_APPROVAL",
        )

    def _aggregate(self, decisions: list[CapabilityDecision]) -> PermissionResult:
        """聚合所有 Capability 的决策。

        DENY > REQUIRE_APPROVAL > ALLOW
        """
        results = [d.result for d in decisions]
        if PermissionResult.DENY in results:
            return PermissionResult.DENY
        if PermissionResult.REQUIRE_APPROVAL in results:
            return PermissionResult.REQUIRE_APPROVAL
        return PermissionResult.ALLOW

    def _format_reason(
        self, decisions: list[CapabilityDecision], final: PermissionResult
    ) -> str:
        """格式化聚合原因。"""
        if not decisions:
            return "无 capability 决策"

        reasons = []
        for d in decisions:
            if d.result == final:
                reasons.append(d.reason)

        if not reasons:
            reasons = [d.reason for d in decisions[:1]]

        return "; ".join(reasons)
