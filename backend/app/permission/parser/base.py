"""ToolParser Protocol + GenericParser。

ToolParser 将 ToolCall 的原始参数解析为 ParsedAction AST。
GenericParser 是兜底实现，直接使用 raw_arguments。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.permission.models import (
    AnalysisCompleteness,
    ParsedAction,
    Redirection,
    new_action_id,
)
from app.runtime.models import ToolCall


@runtime_checkable
class ToolParser(Protocol):
    """Tool 参数解析器接口。"""

    def parse(self, tool_call: ToolCall) -> ParsedAction:
        """解析 ToolCall 为 ParsedAction AST。"""
        ...  # pragma: no cover


class GenericParser:
    """通用解析器——兜底实现。

    不解析参数结构，直接用 raw_arguments。
    """

    def parse(self, tool_call: ToolCall) -> ParsedAction:
        args_list: list[str] = []
        flags: dict[str, Any] = {}

        for key, value in tool_call.arguments.items():
            if isinstance(value, str):
                args_list.append(value)
            else:
                flags[key] = value

        return ParsedAction(
            action_id=new_action_id(),
            executable=tool_call.tool_name,
            args=args_list,
            flags=flags,
            redirections=[],
            operator_before=None,
            children=[],
            raw=str(tool_call.arguments),
            parse_completeness=AnalysisCompleteness.COMPLETE,
            parse_warnings=[],
        )
