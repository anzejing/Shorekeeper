"""ToolRegistry — Tool 注册中心。

独立于 Skill 的基础设施。各模块（Memory、未来插件等）
向 Registry 注册自己的 Tool，Runtime 通过 Registry 执行。

职责：
1. 注册/注销 Tool（ToolDef + 执行器）
2. 提供 tools 列表给 Runtime
3. 路由 ToolCall 到对应执行器
4. 统一异常处理
"""

from __future__ import annotations

import logging
from typing import Any

from app.runtime.models import (
    TextPart,
    ToolCall,
    ToolDef,
    ToolResult,
)

log = logging.getLogger(__name__)


class ToolRegistry:
    """Tool 注册中心。

    每个 Tool 由一个 ToolDef（定义）和一个 executor（执行器）组成。
    executor 需要实现 async def execute(self, tool_call, *, cancellation, context) -> ToolResult。
    """

    def __init__(self) -> None:
        # tool_name → (ToolDef, executor)
        self._tools: dict[str, tuple[ToolDef, Any]] = {}

    def register(self, tool_def: ToolDef, executor: Any) -> None:
        """注册一个 Tool。

        如果同名 Tool 已存在，覆盖并记录警告。

        Args:
            tool_def: 工具定义。
            executor: 工具执行器（需实现 execute 方法）。
        """
        if tool_def.name in self._tools:
            log.warning("Tool '%s' 已存在，将被覆盖", tool_def.name)
        self._tools[tool_def.name] = (tool_def, executor)
        log.info("注册 Tool: %s", tool_def.name)

    def register_many(self, tool_defs: list[ToolDef], executor: Any) -> None:
        """批量注册 Tool（共享同一个执行器）。

        Args:
            tool_defs: 工具定义列表。
            executor: 共享的执行器。
        """
        for td in tool_defs:
            self.register(td, executor)

    def unregister(self, tool_name: str) -> bool:
        """注销一个 Tool。

        Args:
            tool_name: 工具名称。

        Returns:
            是否成功注销。
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            log.info("注销 Tool: %s", tool_name)
            return True
        return False

    def get_all_tools(self) -> list[ToolDef]:
        """获取所有已注册的 ToolDef 列表。"""
        return [td for td, _ in self._tools.values()]

    def get_tool(self, tool_name: str) -> ToolDef | None:
        """按名称获取 ToolDef。"""
        entry = self._tools.get(tool_name)
        return entry[0] if entry else None

    def has_tool(self, tool_name: str) -> bool:
        """检查 Tool 是否已注册。"""
        return tool_name in self._tools

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """执行一个 Tool 调用。

        路由到对应的执行器，统一异常处理。

        Args:
            tool_call: 工具调用请求。
            cancellation: 取消令牌。
            context: 执行上下文。

        Returns:
            ToolResult: 执行结果。
        """
        entry = self._tools.get(tool_call.tool_name)
        if entry is None:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                content=[TextPart(text=f"未知工具: {tool_call.tool_name}")],
                is_error=True,
            )

        tool_def, executor = entry
        try:
            return await executor.execute(
                tool_call,
                cancellation=cancellation,
                context=context,
            )
        except Exception as e:
            log.exception("Tool '%s' 执行失败", tool_call.tool_name)
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                content=[TextPart(text=f"工具执行失败: {e}")],
                is_error=True,
            )
