"""工具执行器接口。

ToolExecutor 负责实际执行工具调用，支持并行/串行、超时、重试。
Agent Loop 将工具调用委托给 ToolExecutor，不直接执行。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.runtime.models import CancellationToken, ToolCall, ToolResult


@runtime_checkable
class ToolExecutor(Protocol):
    """工具执行器接口。

    职责：
    1. 根据 tool_name 查找工具实现
    2. 校验参数
    3. 执行工具（支持超时和重试）
    4. 包装结果或错误为 ToolResult
    """

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: CancellationToken,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """执行单个工具调用。

        Args:
            tool_call: 要执行的工具调用。
            cancellation: 取消令牌。
            context: 执行上下文（run metadata 等）。

        Returns:
            ToolResult: 执行结果。失败时 is_error=True。
        """
        ...  # pragma: no cover
