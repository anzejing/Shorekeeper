"""ToolSearchExecutor — tool_search 工具执行器。

接收自然语言查询，返回匹配工具的完整定义。
供 LLM 发现动态工具（MCP、插件等）。

不负责：
- 工具执行（由 ProxyToolExecutor 负责）
- 索引维护（由 ToolIndex 负责）
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.runtime.models import TextPart, ToolCall, ToolResult
from app.tool.index import ToolIndex

log = logging.getLogger(__name__)


class ToolSearchExecutor:
    """tool_search 工具执行器。

    流程：
    1. 解析查询参数
    2. 在 ToolIndex 中搜索
    3. 格式化返回工具定义（含完整参数 schema）
    """

    def __init__(self, index: ToolIndex) -> None:
        self._index = index

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """执行 tool_search。"""
        query = tool_call.arguments.get("query", "")
        category = tool_call.arguments.get("category")

        if not query.strip():
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="tool_search",
                content=[TextPart(text="错误：请提供搜索关键词。用自然语言描述你需要的功能。")],
                is_error=True,
            )

        # 搜索
        results = self._index.search(query, category=category, limit=5)

        if not results:
            hint = f"（分类: {category}）" if category else ""
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="tool_search",
                content=[TextPart(
                    text=f"未找到匹配 '{query}' 的工具{hint}。\n"
                         f"请尝试其他关键词，或使用 tool_executor 直接调用已知工具。"
                )],
            )

        # 格式化输出
        formatted = self._format_results(results)
        log.info("tool_search: query='%s' → %d 个结果", query, len(results))

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name="tool_search",
            content=[TextPart(text=formatted)],
        )

    def _format_results(self, entries: list) -> str:
        """格式化搜索结果为人类可读文本。"""
        parts = [f"找到 {len(entries)} 个匹配工具：\n"]

        for i, entry in enumerate(entries, 1):
            parts.append(f"## {i}. {entry.name}")
            parts.append(f"描述: {entry.description}")
            parts.append(f"分类: {entry.category}")
            parts.append("")

            # 参数定义
            params = entry.parameters
            properties = params.get("properties", {})
            required = params.get("required", [])

            if properties:
                parts.append("参数:")
                for prop_name, prop_def in properties.items():
                    if not isinstance(prop_def, dict):
                        continue
                    prop_type = prop_def.get("type", "any")
                    is_required = prop_name in required
                    req_label = "必填" if is_required else "可选"

                    # 默认值
                    default = prop_def.get("default")
                    default_label = f", 默认 {default}" if default is not None else ""

                    # enum 值
                    enum_values = prop_def.get("enum")
                    enum_label = f", 可选值: {enum_values}" if enum_values else ""

                    desc = prop_def.get("description", "")

                    parts.append(
                        f"  - {prop_name} ({prop_type}, {req_label}{default_label}{enum_label}): {desc}"
                    )
            else:
                parts.append("参数: 无")

            parts.append("")
            parts.append("---")

        # 使用说明
        parts.append("")
        parts.append(
            "使用方法：调用 tool_executor，"
            "tool_name 填工具名（如 github/list_repos），"
            "arguments 填参数对象。"
        )

        return "\n".join(parts)
