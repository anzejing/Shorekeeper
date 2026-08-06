"""Agent Loop 核心循环。

Runtime 的执行引擎，~200 行核心循环。
模型请求 → 流式事件消费 → 工具调度 → 结果回填 → 下一轮。

依赖接口（均为 Protocol，不引入具体实现）：
- LiteLLMClient: LLM 调用
- ToolExecutor: 工具执行
- InterceptorChain: 拦截器决策
- EventPublisher: 事件发布
- CheckpointStore: 状态持久化
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from app.runtime.checkpoint import CheckpointStore
from app.runtime.event_publisher import EventPublisher
from app.runtime.events import (
    EventType,
    ModelRequestStarted,
    ModelResponseCompleted,
    ModelTextDelta,
    ModelToolCallDelta,
    RunCompleted,
    RunFailed,
    RunStarted,
    RunSuspended,
    RuntimeEvent,
    ToolApprovalRequested,
    ToolCallProposed,
    ToolExecutionCompleted,
    ToolExecutionFailed,
    ToolExecutionStarted,
    UsageUpdated,
    create_event,
)
from app.runtime.interceptor import InterceptorChain
from app.runtime.litellm_client import (
    DONE,
    ERROR,
    TEXT_DELTA,
    TOOL_CALL_DELTA,
    USAGE,
    LiteLLMClient,
    LiteLLMCompletionRequest,
    LiteLLMError,
    LiteLLMStreamEvent,
)
from app.runtime.models import (
    Allow,
    CancellationToken,
    Checkpoint,
    Message,
    Modify,
    PendingWrite,
    Reject,
    Replace,
    Role,
    RunSnapshot,
    RunStatus,
    SuspendDecision,
    ToolCall,
    ToolDef,
    ToolResult,
    Usage,
    new_run_id,
)
from app.runtime.tool_executor import ToolExecutor


# ─── 异常 ─────────────────────────────────────────────────


class MaxStepsExceeded(Exception):
    """Agent Loop 超过最大步数。"""

    def __init__(self, max_steps: int) -> None:
        super().__init__(f"超过最大步数限制: {max_steps}")
        self.max_steps = max_steps


# ─── Run 上下文 ────────────────────────────────────────────


@dataclass
class RunContext:
    """Agent Loop 的运行上下文。

    包含 Run 的状态和所有依赖，Agent Loop 通过它访问外部能力。
    """

    # Run 标识
    run_id: str
    session_id: str
    agent_id: str

    # 状态
    messages: list[Message]
    tools: list[ToolDef]
    max_steps: int

    # 依赖
    llm: LiteLLMClient
    tool_executor: ToolExecutor
    interceptor: InterceptorChain
    publisher: EventPublisher
    checkpoint_store: CheckpointStore

    # 配置
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    llm_extra: dict[str, Any] = field(default_factory=dict)  # LLM provider-specific 配置

    # 运行时
    current_step: int = 0
    event_sequence: int = 0  # 全局事件序列号（跨 step 递增）
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    usage: Usage = field(default_factory=Usage)
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── Agent Loop ───────────────────────────────────────────


class LoopResult:
    """Agent Loop 的执行结果。"""
    def __init__(self, suspended: bool = False, suspension_id: str = ""):
        self.suspended = suspended
        self.suspension_id = suspension_id


async def run_loop(ctx: RunContext) -> LoopResult:
    """Agent Loop 核心循环。

    流程：
    1. 每步开始时 checkpoint
    2. 构造 LLM 请求并流式调用
    3. 收集响应（文本 + 工具调用）
    4. 判断：final answer → RunCompleted / tool calls → 继续
    5. 对每个工具调用执行 Interceptor Chain
    6. Suspend → 退出 / Reject → 回填错误 / Allow/Modify/Replace → 执行
    7. 执行工具，回填结果
    8. checkpoint，进入下一轮

    异常处理：
    - LiteLLMError → RunFailed
    - MaxStepsExceeded → RunFailed
    - Interceptor 异常 → Reject（安全默认）
    - 工具异常 → is_error=True 回填
    """
    # 发布 Run 开始事件
    await _publish(ctx, RunStarted, max_steps=ctx.max_steps)

    try:
        for step in range(ctx.max_steps):
            ctx.current_step = step

            # 检查取消
            await ctx.cancellation.raise_if_cancelled()

            # Step 开始 checkpoint
            await _checkpoint(ctx, step)

            # 模型请求
            response = await _call_llm(ctx, step)

            # 收集流式事件并发布
            collected = await _collect_stream(ctx, response)

            # 将助手回复添加到消息列表
            if collected.tool_calls:
                # 有 tool calls → assistant 消息需要包含 tool_calls 信息
                tool_calls_data = [
                    {
                        "id": tc.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in collected.tool_calls
                ]
                ctx.messages.append(
                    Message(
                        role=Role.ASSISTANT,
                        content=collected.text or "",
                        metadata={"tool_calls": tool_calls_data},
                    )
                )
            elif collected.text:
                ctx.messages.append(
                    Message(role=Role.ASSISTANT, content=collected.text)
                )

            # 判断：final answer 还是 tool calls
            if not collected.tool_calls:
                # Final answer → 完成
                await _publish(
                    ctx,
                    RunCompleted,
                    output=collected.text,
                    usage=ctx.usage,
                )
                return LoopResult(suspended=False)

            # 工具调用路径
            for tool_call in collected.tool_calls:
                # 检查取消
                await ctx.cancellation.raise_if_cancelled()

                # 发布工具提议事件
                await _publish(
                    ctx,
                    ToolCallProposed,
                    tool_call_id=tool_call.tool_call_id,
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments,
                )

                # Interceptor 决策
                decision = await _intercept(ctx, tool_call)

                if isinstance(decision, SuspendDecision):
                    # 暂停 → 发布事件并退出
                    await _publish(
                        ctx,
                        RunSuspended,
                        suspension_id="",  # 由调用方填充
                        suspension_type=decision.request.suspension_type.value,
                        reason=decision.request.reason,
                    )
                    await _publish(
                        ctx,
                        ToolApprovalRequested,
                        approval_id=decision.request.metadata.get("approval_id", ""),
                        tool_call_id=tool_call.tool_call_id,
                        tool_name=tool_call.tool_name,
                        arguments=tool_call.arguments,
                        reason=decision.request.reason,
                    )
                    return LoopResult(suspended=True)

                if isinstance(decision, Reject):
                    # 拒绝 → 回填错误消息给模型
                    ctx.messages.append(
                        Message(
                            role=Role.TOOL,
                            content=f"工具调用被拒绝: {decision.reason}",
                            metadata={"tool_call_id": tool_call.tool_call_id, "is_error": True},
                        )
                    )
                    continue

                if isinstance(decision, Replace):
                    # 替换 → 直接使用替换结果
                    ctx.messages.append(_tool_result_to_message(tool_call, decision.result))
                    continue

                if isinstance(decision, Modify):
                    # 修改参数 → 使用修改后的参数
                    tool_call = ToolCall(
                        tool_call_id=tool_call.tool_call_id,
                        tool_name=tool_call.tool_name,
                        arguments=decision.arguments,
                    )

                # Allow 或 Modify → 执行工具
                result = await _execute_tool(ctx, tool_call)
                ctx.messages.append(_tool_result_to_message(tool_call, result))

            # Step 完成 checkpoint
            await _checkpoint(ctx, step)

        # 超过最大步数
        raise MaxStepsExceeded(ctx.max_steps)

    except MaxStepsExceeded as e:
        await _publish(
            ctx,
            RunFailed,
            error_type="MaxStepsExceeded",
            error_message=str(e),
            is_retryable=False,
        )
        raise
    except asyncio.CancelledError as e:
        await _publish(
            ctx,
            RunFailed,
            error_type="CancelledError",
            error_message=str(e) or "操作已取消",
            is_retryable=False,
        )
        raise
    except LiteLLMError as e:
        await _publish(
            ctx,
            RunFailed,
            error_type="LiteLLMError",
            error_message=str(e),
            is_retryable=e.is_retryable,
        )
        raise
    except Exception as e:
        await _publish(
            ctx,
            RunFailed,
            error_type=type(e).__name__,
            error_message=str(e),
            is_retryable=False,
        )
        raise


# ─── 内部辅助函数 ─────────────────────────────────────────


async def _publish(ctx: RunContext, event_cls: type, **kwargs: Any) -> RuntimeEvent:
    """创建并发布事件。"""
    event = create_event(
        event_cls,
        run_id=ctx.run_id,
        session_id=ctx.session_id,
        sequence=ctx.event_sequence,
        **kwargs,
    )
    ctx.event_sequence += 1
    await ctx.publisher.publish(event)
    return event


async def _checkpoint(ctx: RunContext, step: int) -> None:
    """保存 checkpoint。"""
    snapshot = RunSnapshot(
        run_id=ctx.run_id,
        session_id=ctx.session_id,
        agent_id=ctx.agent_id,
        status=RunStatus.RUNNING,
        version=step,
        messages=list(ctx.messages),
        current_step=step,
        max_steps=ctx.max_steps,
        usage=ctx.usage,
        suspension_id=None,
        execution_attempt=0,
        created_at=_now(),
        updated_at=_now(),
        completed_at=None,
        metadata=ctx.metadata,
    )
    cp = Checkpoint(
        id=f"{ctx.run_id}:step:{step}",
        run_id=ctx.run_id,
        step=step,
        state=snapshot,
        pending_writes=[],
        timestamp=_now(),
    )
    await ctx.checkpoint_store.save(cp)


async def _call_llm(ctx: RunContext, step: int) -> list[LiteLLMStreamEvent]:
    """调用 LLM 并收集所有流式事件。"""
    # 发布模型请求开始事件
    await _publish(ctx, ModelRequestStarted, model=ctx.model, step=step)

    # 构造请求
    request = LiteLLMCompletionRequest(
        model=ctx.model,
        messages=_messages_to_dicts(ctx.messages),
        tools=_tools_to_dicts(ctx.tools) if ctx.tools else None,
        max_tokens=ctx.max_tokens,
        temperature=ctx.temperature,
        extra=dict(ctx.llm_extra),
    )

    # 流式调用
    events = []
    async for event in ctx.llm.stream_completion(
        request, cancellation=ctx.cancellation
    ):
        events.append(event)
    return events


async def _collect_stream(
    ctx: RunContext, events: list[LiteLLMStreamEvent]
) -> _CollectedResponse:
    """收集流式事件为完整响应。"""
    text_parts: list[str] = []
    tool_calls: dict[str, _PartialToolCall] = {}
    usage: Usage | None = None
    finish_reason: str = ""

    for event in events:
        if event.type == TEXT_DELTA and event.content:
            text_parts.append(event.content)
            await _publish(ctx, ModelTextDelta, delta=event.content)

        elif event.type == TOOL_CALL_DELTA:
            tc_id = event.tool_call_id or ""
            if tc_id not in tool_calls:
                tool_calls[tc_id] = _PartialToolCall(
                    tool_call_id=tc_id,
                    tool_name=event.tool_name or "",
                    arguments_parts=[],
                )
            tc = tool_calls[tc_id]
            if event.tool_name:
                tc.tool_name = event.tool_name
            if event.arguments_delta:
                tc.arguments_parts.append(event.arguments_delta)
            await _publish(
                ctx,
                ModelToolCallDelta,
                tool_call_id=tc_id,
                arguments_delta=event.arguments_delta or "",
            )

        elif event.type == USAGE and event.usage:
            usage = event.usage
            ctx.usage.add(usage)
            await _publish(ctx, UsageUpdated, usage=usage)

        elif event.type == DONE:
            finish_reason = event.finish_reason or ""

        elif event.type == ERROR:
            raise LiteLLMError(event.error or "未知错误")

    # 发布模型响应完成事件
    parsed_tool_calls = None
    if tool_calls:
        parsed_tool_calls = [
            {
                "id": tc.tool_call_id,
                "name": tc.tool_name,
                "arguments": _parse_arguments("".join(tc.arguments_parts)),
            }
            for tc in tool_calls.values()
        ]

    await _publish(
        ctx,
        ModelResponseCompleted,
        finish_reason=finish_reason,
        tool_calls=parsed_tool_calls,
        usage=usage,
    )

    # 构造 ToolCall 对象
    result_tool_calls = [
        ToolCall(
            tool_call_id=tc.tool_call_id,
            tool_name=tc.tool_name,
            arguments=_parse_arguments("".join(tc.arguments_parts)),
        )
        for tc in tool_calls.values()
    ]

    return _CollectedResponse(
        text="".join(text_parts),
        tool_calls=result_tool_calls,
        finish_reason=finish_reason,
        usage=usage,
    )


async def _intercept(ctx: RunContext, tool_call: ToolCall) -> Any:
    """执行拦截器链，返回决策。异常时安全默认为 Reject。"""
    try:
        return await ctx.interceptor.process(tool_call)
    except Exception as e:
        return Reject(reason=f"拦截器异常: {e}")


async def _execute_tool(ctx: RunContext, tool_call: ToolCall) -> ToolResult:
    """执行工具调用。"""
    # 发布工具执行开始事件
    await _publish(
        ctx,
        ToolExecutionStarted,
        tool_call_id=tool_call.tool_call_id,
        tool_name=tool_call.tool_name,
        execution_id=f"{ctx.run_id}:tc:{tool_call.tool_call_id}",
    )

    try:
        result = await ctx.tool_executor.execute(
            tool_call, cancellation=ctx.cancellation
        )

        # 发布工具执行完成事件
        await _publish(
            ctx,
            ToolExecutionCompleted,
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            execution_id=f"{ctx.run_id}:tc:{tool_call.tool_call_id}",
            is_error=result.is_error,
        )

        return result

    except Exception as e:
        # 工具异常 → 包装为 is_error=True
        error_result = ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[],
            is_error=True,
        )

        await _publish(
            ctx,
            ToolExecutionFailed,
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            execution_id=f"{ctx.run_id}:tc:{tool_call.tool_call_id}",
            error_type=type(e).__name__,
            error_message=str(e),
        )

        return error_result


def _tool_result_to_message(tool_call: ToolCall, result: ToolResult) -> Message:
    """将工具结果转换为消息。"""
    # 提取文本内容
    content_parts = []
    for part in result.content:
        if hasattr(part, "text"):
            content_parts.append(part.text)

    return Message(
        role=Role.TOOL,
        content="\n".join(content_parts) if content_parts else "",
        metadata={
            "tool_call_id": tool_call.tool_call_id,
            "tool_name": tool_call.tool_name,
            "is_error": result.is_error,
        },
    )


def _messages_to_dicts(messages: list[Message]) -> list[dict[str, Any]]:
    """将 Message 列表转换为 LiteLLM 格式。"""
    result = []
    for msg in messages:
        d: dict[str, Any] = {"role": msg.role.value}
        if isinstance(msg.content, str):
            d["content"] = msg.content
        else:
            # 多模态内容暂不处理，转为字符串
            d["content"] = str(msg.content)

        # Assistant 消息带 tool_calls
        if msg.role == Role.ASSISTANT and "tool_calls" in msg.metadata:
            d["tool_calls"] = msg.metadata["tool_calls"]

        # Tool 消息需要 tool_call_id
        if msg.role == Role.TOOL and "tool_call_id" in msg.metadata:
            d["tool_call_id"] = msg.metadata["tool_call_id"]

        result.append(d)
    return result


def _tools_to_dicts(tools: list[ToolDef]) -> list[dict[str, Any]]:
    """将 ToolDef 列表转换为 LiteLLM 格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _parse_arguments(raw: str) -> dict[str, Any]:
    """解析工具调用参数 JSON。"""
    if not raw:
        return {}
    import json

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def _now() -> Any:
    """获取当前 UTC 时间。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


# ─── 内部数据结构 ──────────────────────────────────────────


@dataclass
class _PartialToolCall:
    """流式收集中的工具调用。"""

    tool_call_id: str
    tool_name: str
    arguments_parts: list[str]


@dataclass
class _CollectedResponse:
    """收集后的完整模型响应。"""

    text: str
    tool_calls: list[ToolCall]
    finish_reason: str
    usage: Usage | None
