"""Rule Matcher — 权限规则匹配逻辑。

职责：
1. 按 layer → specificity → priority → tie-breaker 排序
2. conditions 匹配
3. arguments_pattern 约束（只能收紧，不能放松）

不做参数解析——那是 Parser/Analyzer 的职责。
"""

from __future__ import annotations

import fnmatch
from typing import Any

from app.permission.models import (
    PermissionDecision,
    PermissionResult,
    PermissionRule,
    PermissionRuleLayer,
    ResolvedCapability,
)
from app.runtime.models import ToolCall


# ─── 规则层级排序 ─────────────────────────────────────────

LAYER_ORDER = {
    PermissionRuleLayer.SYSTEM_GUARDRAIL: 0,
    PermissionRuleLayer.SESSION_OVERRIDE: 1,
    PermissionRuleLayer.PROJECT_RULE: 2,
    PermissionRuleLayer.USER_GLOBAL_RULE: 3,
    PermissionRuleLayer.BUILTIN_DEFAULT: 4,
}

# ─── 决策严重度（同层冲突时取最严格）───────────────────────

RESULT_RANK = {
    PermissionResult.ALLOW: 0,
    PermissionResult.REQUIRE_APPROVAL: 1,
    PermissionResult.DENY: 2,
}


def sort_rules(rules: list[PermissionRule]) -> list[PermissionRule]:
    """按优先级排序规则。

    顺序：layer(升序) → specificity(降序) → priority(降序) → rule_id(字典序)
    """
    return sorted(rules, key=lambda r: (
        LAYER_ORDER.get(r.layer, 99),
        -_specificity(r),
        -r.priority,
        r.rule_id,
    ))


def _specificity(rule: PermissionRule) -> int:
    """计算规则的具体度。"""
    score = 0
    if rule.capability:
        score += 10
    if rule.tool_name:
        score += 5
    if rule.arguments_pattern:
        score += 3
    if rule.conditions:
        score += len(rule.conditions) * 2
    return score


def match_conditions(
    rule: PermissionRule,
    capability: ResolvedCapability,
    tool_call: ToolCall,
) -> bool:
    """检查规则的 conditions 是否匹配。"""
    if not rule.conditions:
        return True

    for key, expected in rule.conditions.items():
        actual = _resolve_condition(key, capability, tool_call)
        if actual is None:
            return False
        if not _condition_matches(expected, actual):
            return False

    return True


def _resolve_condition(
    key: str,
    capability: ResolvedCapability,
    tool_call: ToolCall,
) -> Any:
    """从 capability metadata 或 tool_call 中提取条件值。"""
    # 优先从 capability metadata 取
    if key in capability.metadata:
        return capability.metadata[key]
    # 从 tool_call arguments 取
    if key in tool_call.arguments:
        return tool_call.arguments[key]
    return None


def _condition_matches(expected: Any, actual: Any) -> bool:
    """条件匹配。"""
    if isinstance(expected, bool):
        return actual == expected
    if isinstance(expected, str):
        if isinstance(actual, str):
            return fnmatch.fnmatch(actual, expected)
        return str(actual) == expected
    if isinstance(expected, (int, float)):
        return actual == expected
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def apply_pattern_constraint(
    base: PermissionResult,
    pattern_result: PermissionResult,
) -> PermissionResult:
    """arguments_pattern 只能收紧限制，不能放松。

    ALLOW → REQUIRE_APPROVAL / DENY：允许
    REQUIRE_APPROVAL → ALLOW：禁止（保持 REQUIRE_APPROVAL）
    DENY → ALLOW：禁止（保持 DENY）
    """
    if RESULT_RANK[pattern_result] > RESULT_RANK[base]:
        return pattern_result
    return base


def match_arguments_pattern(pattern: str, tool_call: ToolCall) -> bool:
    """检查 arguments_pattern 是否匹配 tool_call 的参数。"""
    # 从 arguments 中提取 command 或拼接所有值
    command = tool_call.arguments.get("command", "")
    if not command:
        command = " ".join(str(v) for v in tool_call.arguments.values())
    return fnmatch.fnmatch(command, pattern)
