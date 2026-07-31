"""拦截器接口。

InterceptorChain 对工具调用进行拦截决策：
Allow / Modify / Reject / Replace / Suspend。
Agent Loop 在执行工具前调用，根据决策控制执行流程。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.runtime.models import ToolCall, ToolDecision


@runtime_checkable
class InterceptorChain(Protocol):
    """拦截器链接口。

    按注册顺序执行多个 Interceptor，返回最终决策。
    决策优先级：Suspend > Reject > Replace > Modify > Allow。
    异常时安全默认为 Reject。
    """

    async def process(self, tool_call: ToolCall) -> ToolDecision:
        """对工具调用执行拦截器链。

        Args:
            tool_call: 模型请求的工具调用。

        Returns:
            ToolDecision: Allow/Modify/Reject/Replace/SuspendDecision。
        """
        ...  # pragma: no cover
