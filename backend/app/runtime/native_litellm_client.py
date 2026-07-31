"""NativeLiteLLMClient — LiteLLMClient Protocol 的真实实现。

调用 litellm.acompletion 进行流式 LLM 调用，
将 litellm 原始响应规范化为 LiteLLMStreamEvent。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from litellm import acompletion
from litellm.types.utils import ModelResponse

from app.runtime.litellm_client import (
    DONE,
    ERROR,
    REASONING_DELTA,
    TEXT_DELTA,
    TOOL_CALL_DELTA,
    USAGE,
    LiteLLMClient,
    LiteLLMCompletionRequest,
    LiteLLMError,
    LiteLLMStreamEvent,
)
from app.runtime.models import CancellationToken, Usage


class NativeLiteLLMClient:
    """LiteLLMClient 的真实实现。

    使用 litellm.acompletion 调用模型，支持流式输出。
    将 litellm 的 chunk 格式规范化为 LiteLLMStreamEvent。
    """

    async def stream_completion(
        self,
        request: LiteLLMCompletionRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[LiteLLMStreamEvent]:
        """流式调用 LLM。"""
        # 构造 litellm 参数
        # 处理 OpenAI 兼容的自定义 endpoint
        extra = dict(request.extra)
        model = request.model

        # 如果有 api_base 且 model 没有 provider 前缀，自动加 openai/
        api_base = extra.pop("base_url", None) or extra.pop("api_base", None)
        if api_base and "/" not in model:
            model = f"openai/{model}"
            extra["api_base"] = api_base

        # api_key 从 extra 提取
        api_key = extra.pop("api_key", None)

        kwargs: dict = {
            "model": model,
            "messages": request.messages,
            "stream": True,
        }
        if request.tools:
            kwargs["tools"] = request.tools
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if api_key:
            kwargs["api_key"] = api_key
        # 合并 provider-specific kwargs
        kwargs.update(extra)

        try:
            response = await acompletion(**kwargs)

            # 遍历流式 chunk
            tool_call_buffers: dict[int, _ToolCallBuffer] = {}

            async for chunk in response:  # type: ignore
                # 检查取消
                if cancellation.is_cancelled:
                    yield LiteLLMStreamEvent(
                        type=ERROR, error="操作已取消"
                    )
                    return

                # 处理 chunk
                delta = _extract_delta(chunk)
                if delta is None:
                    continue

                # 文本 delta
                content = delta.get("content")
                if content:
                    yield LiteLLMStreamEvent(type=TEXT_DELTA, content=content)

                # 推理 delta（部分模型支持）
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning:
                    yield LiteLLMStreamEvent(
                        type=REASONING_DELTA, content=reasoning
                    )

                # 工具调用 delta
                tool_calls = delta.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        idx = tc.get("index", 0)
                        if idx not in tool_call_buffers:
                            tool_call_buffers[idx] = _ToolCallBuffer()

                        buf = tool_call_buffers[idx]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            buf.name = fn["name"]
                            buf.id = tc.get("id", buf.id)
                        if fn.get("arguments"):
                            buf.arguments_parts.append(fn["arguments"])

                        yield LiteLLMStreamEvent(
                            type=TOOL_CALL_DELTA,
                            tool_call_id=buf.id,
                            tool_name=fn.get("name"),
                            arguments_delta=fn.get("arguments"),
                        )

                # finish_reason
                finish_reason = _extract_finish_reason(chunk)
                if finish_reason:
                    # 收集 usage
                    usage = _extract_usage(chunk)
                    if usage:
                        yield LiteLLMStreamEvent(type=USAGE, usage=usage)

                    yield LiteLLMStreamEvent(
                        type=DONE,
                        finish_reason=finish_reason,
                        usage=usage,
                    )

        except asyncio.CancelledError:
            yield LiteLLMStreamEvent(type=ERROR, error="操作已取消")
            return
        except Exception as e:
            yield LiteLLMStreamEvent(type=ERROR, error=str(e))
            raise LiteLLMError(
                str(e),
                is_retryable=_is_retryable(e),
                provider_error=e,
            ) from e


def _extract_delta(chunk: ModelResponse) -> dict | None:
    """从 litellm chunk 中提取 delta。"""
    try:
        choices = chunk.choices
        if not choices:
            return None
        delta = choices[0].delta
        if delta is None:
            return None
        return delta.model_dump() if hasattr(delta, "model_dump") else dict(delta)
    except (AttributeError, IndexError):
        return None


def _extract_finish_reason(chunk: ModelResponse) -> str | None:
    """从 chunk 中提取 finish_reason。"""
    try:
        choices = chunk.choices
        if not choices:
            return None
        reason = choices[0].finish_reason
        return reason if reason else None
    except (AttributeError, IndexError):
        return None


def _extract_usage(chunk: ModelResponse) -> Usage | None:
    """从 chunk 中提取 usage。"""
    try:
        if not hasattr(chunk, "usage") or chunk.usage is None:
            return None
        u = chunk.usage
        return Usage(
            input_tokens=getattr(u, "prompt_tokens", 0) or 0,
            output_tokens=getattr(u, "completion_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            total_tokens=getattr(u, "total_tokens", 0) or 0,
        )
    except (AttributeError, TypeError):
        return None


def _is_retryable(error: Exception) -> bool:
    """判断错误是否可重试。"""
    error_str = str(error).lower()
    # 429 rate limit, 503 service unavailable
    return any(code in error_str for code in ["429", "503", "rate limit", "timeout"])


class _ToolCallBuffer:
    """流式工具调用的缓冲区。"""

    def __init__(self) -> None:
        self.id: str = ""
        self.name: str = ""
        self.arguments_parts: list[str] = []
