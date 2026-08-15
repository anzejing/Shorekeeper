"""NativeLiteLLMClient — LiteLLMClient Protocol 的真实实现。

调用 litellm.acompletion 进行流式 LLM 调用，
将 litellm 原始响应规范化为 LiteLLMStreamEvent。

支持代理：provider.use_proxy 开启时，通过预建 AsyncOpenAI（httpx proxy client）
走代理；代理连接失败（首包前）自动回退直连重试一次。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx
from litellm import acompletion
from litellm.types.utils import ModelResponse
from openai import AsyncOpenAI

from app.config.service import ConfigService
from app.net.proxy import (
    build_proxy_client,
    chain_first,
    close_proxy_client,
    fallback_direct_enabled,
    get_proxy_url,
    is_conn_error,
)
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

log = logging.getLogger(__name__)


class NativeLiteLLMClient:
    """LiteLLMClient 的真实实现。

    使用 litellm.acompletion 调用模型，支持流式输出。
    将 litellm 的 chunk 格式规范化为 LiteLLMStreamEvent。
    """

    def __init__(self, config_service: ConfigService | None = None) -> None:
        self._config = config_service or ConfigService.get_instance()

    async def stream_completion(
        self,
        request: LiteLLMCompletionRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[LiteLLMStreamEvent]:
        """流式调用 LLM。"""
        # 构造 litellm 参数
        extra = dict(request.extra)
        model = request.model

        # api_base 透传（模型名已含 provider 前缀，由模型配置生成，不再自动猜测）
        api_base = extra.pop("base_url", None) or extra.pop("api_base", None)
        if api_base:
            extra["api_base"] = api_base

        # api_key 从 extra 提取
        api_key = extra.pop("api_key", None)

        # use_proxy：provider 是否走代理（不入 litellm kwargs）
        use_proxy = bool(extra.pop("use_proxy", False))

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

        # 代理：provider.use_proxy 开启且全局代理配置可用时，走代理
        proxy_client: AsyncOpenAI | None = None
        if use_proxy:
            proxy_url = get_proxy_url(self._config)
            if proxy_url:
                proxy_client = build_proxy_client(
                    proxy_url, api_key, api_base
                )
                kwargs["client"] = proxy_client

        try:
            # 首包前代理连接失败 → 直连重试一次
            chunks = self._iter_completion(kwargs, cancellation)
            try:
                first = await chunks.__anext__()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if (
                    proxy_client is not None
                    and fallback_direct_enabled(self._config)
                    and is_conn_error(e)
                ):
                    log.warning("LLM 请求代理失败，回退直连: %s", e)
                    await chunks.aclose()
                    await close_proxy_client(proxy_client)
                    proxy_client = None
                    kwargs.pop("client", None)
                    chunks = self._iter_completion(kwargs, cancellation)
                    first = await chunks.__anext__()
                else:
                    yield LiteLLMStreamEvent(type=ERROR, error=str(e))
                    raise LiteLLMError(
                        str(e),
                        is_retryable=_is_retryable(e),
                        provider_error=e,
                    ) from e

            # 处理首个 chunk + 后续流
            async for event in self._iter_events(
                chunks, first, cancellation
            ):
                yield event

        except asyncio.CancelledError:
            yield LiteLLMStreamEvent(type=ERROR, error="操作已取消")
            return
        except LiteLLMError:
            raise
        except Exception as e:
            yield LiteLLMStreamEvent(type=ERROR, error=str(e))
            raise LiteLLMError(
                str(e),
                is_retryable=_is_retryable(e),
                provider_error=e,
            ) from e
        finally:
            if proxy_client is not None:
                await close_proxy_client(proxy_client)

    async def _iter_completion(
        self, kwargs: dict, cancellation: CancellationToken
    ) -> AsyncIterator[Any]:
        """调用 acompletion 并迭代原始 chunk（异常原样抛出）。"""
        response = await acompletion(**kwargs)
        async for chunk in response:  # type: ignore
            yield chunk

    async def _iter_events(
        self,
        chunks: AsyncIterator[Any],
        first: Any,
        cancellation: CancellationToken,
    ) -> AsyncIterator[LiteLLMStreamEvent]:
        """将首 chunk 与后续 chunk 流转换为规范事件流。"""
        tool_call_buffers: dict[int, _ToolCallBuffer] = {}
        async for chunk in chain_first(first, chunks):
            # 检查取消
            if cancellation.is_cancelled:
                yield LiteLLMStreamEvent(type=ERROR, error="操作已取消")
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
