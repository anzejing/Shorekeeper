"""CapabilityAnalyzer Protocol + GenericAnalyzer。

CapabilityAnalyzer 将 ParsedAction 分析为 ResolvedCapability。
GenericAnalyzer 是兜底实现，按 tool_name 推断。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.permission.models import (
    AnalysisCompleteness,
    CapabilityAnalysis,
    ParsedAction,
    ResolvedCapability,
)
from app.runtime.models import ToolCall


@runtime_checkable
class CapabilityAnalyzer(Protocol):
    """能力分析器接口。"""

    def analyze(self, parsed: ParsedAction, tool_call: ToolCall) -> CapabilityAnalysis:
        """分析 ParsedAction 为 CapabilityAnalysis。"""
        ...  # pragma: no cover


class GenericAnalyzer:
    """通用分析器——兜底实现。

    无法识别具体能力时，返回 REQUIRE_APPROVAL 级别的能力。
    不做任何安全推断。
    """

    def analyze(self, parsed: ParsedAction, tool_call: ToolCall) -> CapabilityAnalysis:
        # 未知工具 → system.execute_unknown
        return CapabilityAnalysis(
            capabilities=[
                ResolvedCapability(
                    capability="system.execute_unknown",
                    metadata={
                        "tool_name": tool_call.tool_name,
                        "executable": parsed.executable,
                        "raw": parsed.raw,
                    },
                    source_action_id=parsed.action_id,
                    completeness=parsed.parse_completeness,
                    warnings=parsed.parse_warnings + [f"未知工具: {tool_call.tool_name}"],
                )
            ],
            completeness=parsed.parse_completeness,
            warnings=parsed.parse_warnings + [f"未知工具: {tool_call.tool_name}，使用通用分析"],
        )
