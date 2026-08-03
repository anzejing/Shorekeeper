"""Runtime API 路由。

对外暴露 Run 生命周期管理接口：
- POST /api/runs — 创建 Run
- POST /api/runs/{run_id}/execute — 启动执行
- GET /api/runs/{run_id}/stream — SSE 事件流
- POST /api/runs/{run_id}/resume — 恢复暂停
- POST /api/runs/{run_id}/cancel — 取消
- GET /api/runs/{run_id} — 查询状态
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.runtime.models import (
    Message,
    ResumeInput,
    Role,
    RunHandle,
    RunRequest,
    RunSnapshot,
    RunStatus,
    Usage,
)
from app.runtime.runtime import NativePythonRuntime, RunNotFoundError

router = APIRouter()

# ─── 全局 Runtime 实例（由 main.py 注入） ─────────────────

_runtime: NativePythonRuntime | None = None


def set_runtime(runtime: NativePythonRuntime) -> None:
    """设置全局 Runtime 实例。"""
    global _runtime
    _runtime = runtime


def get_runtime() -> NativePythonRuntime:
    """获取 Runtime 实例。"""
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Runtime 未初始化")
    return _runtime


# ─── 请求/响应模型 ────────────────────────────────────────


class CreateRunRequest(BaseModel):
    """创建 Run 请求。"""

    session_id: str
    agent_id: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    max_steps: int = 20
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeRequest(BaseModel):
    """恢复 Run 请求。"""

    approved: bool
    idempotency_key: str
    result: dict[str, Any] | None = None
    reason: str | None = None


class CancelRequest(BaseModel):
    """取消 Run 请求。"""

    reason: str | None = None


class RunHandleResponse(BaseModel):
    """Run 句柄响应。"""

    run_id: str
    status: str
    created_at: str


class RunSnapshotResponse(BaseModel):
    """Run 快照响应。"""

    run_id: str
    session_id: str
    agent_id: str
    status: str
    version: int
    current_step: int
    max_steps: int
    messages: list[dict[str, Any]]
    usage: dict[str, Any]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    completed_at: str | None


# ─── 接口实现 ─────────────────────────────────────────────


@router.post("/runs", response_model=RunHandleResponse)
async def create_run(request: CreateRunRequest) -> RunHandleResponse:
    """创建 Run。"""
    runtime = get_runtime()

    # 构造领域模型
    messages = [
        Message(
            role=Role(m.get("role", "user")),
            content=m.get("content", ""),
        )
        for m in request.messages
    ]

    run_request = RunRequest(
        session_id=request.session_id,
        agent_id=request.agent_id,
        messages=messages,
        max_steps=request.max_steps,
        metadata=request.metadata,
    )

    handle = await runtime.create_run(run_request)

    return RunHandleResponse(
        run_id=handle.run_id,
        status=handle.status.value,
        created_at=handle.created_at.isoformat(),
    )


@router.post("/runs/{run_id}/execute")
async def execute_run(run_id: str) -> dict[str, str]:
    """启动 Run 执行。"""
    runtime = get_runtime()
    try:
        await runtime.execute(run_id)
        return {"status": "executing"}
    except RunNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, after_sequence: int = -1) -> StreamingResponse:
    """SSE 事件流。

    通过 EventStore 查询事件并以 SSE 格式推送。
    支持 after_sequence 参数用于断线补发。
    """
    runtime = get_runtime()

    # 验证 Run 存在
    try:
        await runtime.get_run(run_id)
    except RunNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    async def event_generator():
        """SSE 事件生成器。"""
        seen_sequences: set[int] = set()
        event_store = getattr(runtime, "_event_store", None)

        # 先推送历史事件
        if event_store is not None:
            events = await event_store.list_by_run(
                run_id, after_sequence=after_sequence
            )
            for event in events:
                if event.sequence not in seen_sequences:
                    seen_sequences.add(event.sequence)
                    yield _format_sse(event)

        # 轮询新事件（简化实现，生产环境应用 WebSocket 或长轮询）
        import asyncio

        last_sequence = max(seen_sequences) if seen_sequences else after_sequence
        max_iterations = 3000  # 最多轮询 5 分钟（每秒 10 次）
        idle_count = 0

        for _ in range(max_iterations):
            await asyncio.sleep(0.1)

            if event_store is not None:
                events = await event_store.list_by_run(
                    run_id, after_sequence=last_sequence
                )
                for event in events:
                    if event.sequence not in seen_sequences:
                        seen_sequences.add(event.sequence)
                        last_sequence = max(last_sequence, event.sequence)
                        idle_count = 0
                        yield _format_sse(event)

            # 检查 Run 是否已结束
            try:
                snapshot = await runtime.get_run(run_id)
                if snapshot.status in {
                    RunStatus.COMPLETED,
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                    RunStatus.TERMINATED,
                }:
                    # 等待一小段时间确保所有事件都已推送
                    await asyncio.sleep(0.2)
                    if hasattr(runtime, "_event_store"):
                        events = await runtime._event_store.list_by_run(
                            run_id, after_sequence=last_sequence
                        )
                        for event in events:
                            if event.sequence not in seen_sequences:
                                yield _format_sse(event)
                    break
            except RunNotFoundError:
                break

            idle_count += 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/resume", response_model=RunHandleResponse)
async def resume_run(run_id: str, request: ResumeRequest) -> RunHandleResponse:
    """恢复暂停的 Run。"""
    runtime = get_runtime()

    resume_input = ResumeInput(
        approved=request.approved,
        idempotency_key=request.idempotency_key,
        reason=request.reason,
    )

    try:
        handle = await runtime.resume(run_id, resume_input)
        return RunHandleResponse(
            run_id=handle.run_id,
            status=handle.status.value,
            created_at=handle.created_at.isoformat(),
        )
    except RunNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: CancelRequest | None = None) -> dict[str, str]:
    """取消 Run。"""
    runtime = get_runtime()
    reason = request.reason if request else None

    try:
        await runtime.cancel(run_id, reason=reason)
        return {"status": "cancelled"}
    except RunNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/runs/{run_id}", response_model=RunSnapshotResponse)
async def get_run(run_id: str) -> RunSnapshotResponse:
    """查询 Run 状态。"""
    runtime = get_runtime()

    try:
        snapshot = await runtime.get_run(run_id)
        return _snapshot_to_response(snapshot)
    except RunNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── 辅助函数 ─────────────────────────────────────────────


def _format_sse(event: Any) -> str:
    """将事件格式化为 SSE 格式。"""
    data = {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "timestamp": event.timestamp.isoformat(),
    }
    # 添加事件特有字段
    if hasattr(event, "delta"):
        data["delta"] = event.delta
    if hasattr(event, "output"):
        data["output"] = event.output
    if hasattr(event, "error_type"):
        data["error_type"] = event.error_type
    if hasattr(event, "error_message"):
        data["error_message"] = event.error_message
    if hasattr(event, "tool_name"):
        data["tool_name"] = event.tool_name

    return f"event: {event.event_type.value}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _snapshot_to_response(snapshot: RunSnapshot) -> RunSnapshotResponse:
    """将 RunSnapshot 转换为响应模型。"""
    messages = []
    for msg in snapshot.messages:
        m: dict[str, Any] = {"role": msg.role.value}
        if isinstance(msg.content, str):
            m["content"] = msg.content
        else:
            m["content"] = str(msg.content)
        messages.append(m)

    usage_dict = asdict(snapshot.usage)

    return RunSnapshotResponse(
        run_id=snapshot.run_id,
        session_id=snapshot.session_id,
        agent_id=snapshot.agent_id,
        status=snapshot.status.value,
        version=snapshot.version,
        current_step=snapshot.current_step,
        max_steps=snapshot.max_steps,
        messages=messages,
        usage=usage_dict,
        metadata=snapshot.metadata,
        created_at=snapshot.created_at.isoformat(),
        updated_at=snapshot.updated_at.isoformat(),
        completed_at=snapshot.completed_at.isoformat() if snapshot.completed_at else None,
    )
