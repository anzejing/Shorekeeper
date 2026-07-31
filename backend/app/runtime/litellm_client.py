"""LiteLLM 薄封装——接口层。

定义 LLM 调用的 Protocol 接口和数据模型。
Agent Loop 依赖此接口，不直接依赖 litellm 库。
具体实现在 NativePythonRuntime 组装阶段提供。

不引入 litellm 依赖，保持纯接口层。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from app.runtime.models import CancellationToken, Usage


# ─── 请求模型 ─────────────────────────────────────────────


@dataclass
class LiteLLMCompletionRequest:
    """LiteLLM 请求。

    由 Agent Loop 从 Run.messages + Run.tools 构建。
    extra 字段传递 provider-specific kwargs，不污染核心接口。
    """

    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


# ─── 流式事件 ─────────────────────────────────────────────


@dataclass
class LiteLLMStreamEvent:
    """LiteLLM 流式事件。

    规范化后的流式响应 chunk，由实现层产生，Agent Loop 消费。

    type 字段区分事件类型：
    - text_delta: 文本增量
    - reasoning_delta: 推理增量
    - tool_call_delta: 工具调用参数增量
    - usage: 使用量统计
    - done: 流结束（含 finish_reason）
    - error: 错误
    """

    type: str
    content: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str | None = None
    usage: Usage | None = None
    finish_reason: str | None = None
    error: str | None = None
    raw_response: dict[str, Any] | None = None


# ─── 事件类型常量 ──────────────────────────────────────────

TEXT_DELTA = "text_delta"
REASONING_DELTA = "reasoning_delta"
TOOL_CALL_DELTA = "tool_call_delta"
USAGE = "usage"
DONE = "done"
ERROR = "error"


# ─── Protocol 接口 ─────────────────────────────────────────


@runtime_checkable
class LiteLLMClient(Protocol):
    """LiteLLM 客户端接口。

    Agent Loop 通过此接口调用 LLM，不关心底层实现。
    实现层负责：
    1. 调用 litellm.acompletion（或其他 provider SDK）
    2. 将原始响应规范化为 LiteLLMStreamEvent
    3. 处理重试、超时等 provider 级错误
    """

    async def stream_completion(
        self,
        request: LiteLLMCompletionRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[LiteLLMStreamEvent]:
        """流式调用 LLM。

        Args:
            request: 构建好的 LLM 请求。
            cancellation: 取消令牌，实现层需检查并在取消时中止。

        Yields:
            LiteLLMStreamEvent: 规范化的流式事件。

        Raises:
            LiteLLMError: 调用失败（含重试信息）。
        """
        ...  # pragma: no cover
        # 使 async generator 语法合法
        yield  # type: ignore[misc]


# ─── 错误类型 ──────────────────────────────────────────────


class LiteLLMError(Exception):
    """LiteLLM 调用错误。

    包含重试信息，由实现层抛出，Agent Loop 捕获处理。
    """

    def __init__(
        self,
        message: str,
        *,
        is_retryable: bool = False,
        retry_after: float | None = None,
        provider_error: Any = None,
    ) -> None:
        super().__init__(message)
        self.is_retryable = is_retryable
        self.retry_after = retry_after
        self.provider_error = provider_error
