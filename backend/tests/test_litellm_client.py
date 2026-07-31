"""LiteLLM 薄封装接口层测试。"""

from __future__ import annotations

import asyncio
from dataclasses import fields

import pytest

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


# ─── CancellationToken ────────────────────────────────────


class TestCancellationToken:
    def test_initial_state(self) -> None:
        ct = CancellationToken()
        assert ct.is_cancelled is False
        assert ct.reason == ""

    def test_cancel_sets_flag(self) -> None:
        ct = CancellationToken()
        ct.cancel("用户取消")
        assert ct.is_cancelled is True
        assert ct.reason == "用户取消"

    def test_cancel_without_reason(self) -> None:
        ct = CancellationToken()
        ct.cancel()
        assert ct.is_cancelled is True
        assert ct.reason == ""

    @pytest.mark.asyncio
    async def test_wait_returns_after_cancel(self) -> None:
        ct = CancellationToken()
        # 先触发取消，再 wait 应立即返回
        ct.cancel()
        await asyncio.wait_for(ct.wait(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_raise_if_cancelled_not_cancelled(self) -> None:
        ct = CancellationToken()
        # 不应抛出
        await ct.raise_if_cancelled()

    @pytest.mark.asyncio
    async def test_raise_if_cancelled_when_cancelled(self) -> None:
        ct = CancellationToken()
        ct.cancel("测试取消")
        with pytest.raises(asyncio.CancelledError, match="测试取消"):
            await ct.raise_if_cancelled()


# ─── LiteLLMCompletionRequest ─────────────────────────────


class TestLiteLLMCompletionRequest:
    def test_minimal_request(self) -> None:
        req = LiteLLMCompletionRequest(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert req.model == "gpt-4o"
        assert req.messages == [{"role": "user", "content": "hello"}]
        assert req.tools is None
        assert req.max_tokens is None
        assert req.temperature is None
        assert req.stream is True
        assert req.extra == {}

    def test_full_request(self) -> None:
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        req = LiteLLMCompletionRequest(
            model="claude-sonnet-4-20250514",
            messages=[{"role": "user", "content": "读文件"}],
            tools=tools,
            max_tokens=4096,
            temperature=0.7,
            stream=False,
            extra={"api_key": "sk-xxx"},
        )
        assert req.tools == tools
        assert req.max_tokens == 4096
        assert req.temperature == 0.7
        assert req.stream is False
        assert req.extra == {"api_key": "sk-xxx"}

    def test_fields_have_defaults(self) -> None:
        """除 model 和 messages 外，其他字段都有默认值。"""
        field_names = {f.name for f in fields(LiteLLMCompletionRequest)}
        required = {"model", "messages"}
        optional = field_names - required
        assert optional == {"tools", "max_tokens", "temperature", "stream", "extra"}


# ─── LiteLLMStreamEvent ───────────────────────────────────


class TestLiteLLMStreamEvent:
    def test_text_delta(self) -> None:
        event = LiteLLMStreamEvent(type=TEXT_DELTA, content="hello")
        assert event.type == TEXT_DELTA
        assert event.content == "hello"
        assert event.tool_call_id is None

    def test_tool_call_delta(self) -> None:
        event = LiteLLMStreamEvent(
            type=TOOL_CALL_DELTA,
            tool_call_id="tc-001",
            tool_name="read_file",
            arguments_delta='{"path":',
        )
        assert event.type == TOOL_CALL_DELTA
        assert event.tool_call_id == "tc-001"
        assert event.tool_name == "read_file"

    def test_usage_event(self) -> None:
        usage = Usage(input_tokens=100, output_tokens=50)
        event = LiteLLMStreamEvent(type=USAGE, usage=usage)
        assert event.type == USAGE
        assert event.usage is not None
        assert event.usage.input_tokens == 100

    def test_done_event(self) -> None:
        event = LiteLLMStreamEvent(type=DONE, finish_reason="stop")
        assert event.type == DONE
        assert event.finish_reason == "stop"

    def test_error_event(self) -> None:
        event = LiteLLMStreamEvent(type=ERROR, error="rate limit exceeded")
        assert event.type == ERROR
        assert event.error == "rate limit exceeded"

    def test_raw_response_preserved(self) -> None:
        raw = {"id": "chatcmpl-123", "model": "gpt-4o"}
        event = LiteLLMStreamEvent(type=DONE, raw_response=raw)
        assert event.raw_response == raw


# ─── 事件类型常量 ──────────────────────────────────────────


class TestStreamEventConstants:
    def test_all_constants_defined(self) -> None:
        assert TEXT_DELTA == "text_delta"
        assert REASONING_DELTA == "reasoning_delta"
        assert TOOL_CALL_DELTA == "tool_call_delta"
        assert USAGE == "usage"
        assert DONE == "done"
        assert ERROR == "error"


# ─── LiteLLMClient Protocol ───────────────────────────────


class TestLiteLLMClientProtocol:
    def test_protocol_is_runtime_checkable(self) -> None:
        """Protocol 可用于 isinstance 检查。"""

        class DummyClient:
            async def stream_completion(self, request, *, cancellation):
                yield LiteLLMStreamEvent(type=DONE)

        client = DummyClient()
        assert isinstance(client, LiteLLMClient)

    def test_non_conforming_not_instance(self) -> None:
        """缺少方法的类不是 Protocol 实例。"""

        class NotAClient:
            pass

        assert not isinstance(NotAClient(), LiteLLMClient)


# ─── LiteLLMError ─────────────────────────────────────────


class TestLiteLLMError:
    def test_basic_error(self) -> None:
        err = LiteLLMError("调用失败")
        assert str(err) == "调用失败"
        assert err.is_retryable is False
        assert err.retry_after is None
        assert err.provider_error is None

    def test_retryable_error(self) -> None:
        err = LiteLLMError(
            "rate limit",
            is_retryable=True,
            retry_after=30.0,
            provider_error={"status_code": 429},
        )
        assert err.is_retryable is True
        assert err.retry_after == 30.0
        assert err.provider_error == {"status_code": 429}

    def test_is_exception_subclass(self) -> None:
        assert issubclass(LiteLLMError, Exception)
