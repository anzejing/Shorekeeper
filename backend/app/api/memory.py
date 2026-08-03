"""Memory HTTP API。

提供会话管理、消息管理、长期记忆管理、搜索的 REST 接口。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.memory.models import (
    AddMessageRequest,
    CreateMemoryRequest,
    CreateSessionRequest,
    MemoryEntryResponse,
    MemoryListResponse,
    MessageListResponse,
    MessageResponse,
    SearchRequest,
    SearchResponse,
    SessionListResponse,
    SessionResponse,
    UpdateMemoryRequest,
)
from app.memory.service import MemoryService

router = APIRouter(prefix="/api/memory", tags=["memory"])

# MemoryService 实例由 main.py 注入
_service: MemoryService | None = None


def init_memory_api(service: MemoryService) -> None:
    """初始化 Memory API，注入 MemoryService。"""
    global _service
    _service = service


def _get_service() -> MemoryService:
    """获取 MemoryService 实例。"""
    if _service is None:
        raise HTTPException(status_code=503, detail="Memory 模块未初始化")
    return _service


# ─── 会话管理 ─────────────────────────────────────────────


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(request: CreateSessionRequest) -> SessionResponse:
    """创建会话。"""
    service = _get_service()
    return await service.create_session(
        title=request.title,
        metadata=request.metadata,
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SessionListResponse:
    """列出会话。"""
    service = _get_service()
    return await service.list_sessions(limit=limit, offset=offset)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """获取会话。"""
    service = _get_service()
    result = await service.get_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return result


@router.put("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SessionResponse:
    """更新会话。"""
    service = _get_service()
    try:
        return await service.update_session(
            session_id=session_id,
            title=title,
            metadata=metadata,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> None:
    """删除会话。"""
    service = _get_service()
    deleted = await service.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")


# ─── 消息管理 ─────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/messages", response_model=MessageListResponse
)
async def get_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    before: datetime | None = Query(default=None),
) -> MessageListResponse:
    """获取会话消息。"""
    service = _get_service()
    # 检查会话存在
    session = await service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return await service.get_messages(
        session_id=session_id,
        limit=limit,
        offset=offset,
        before=before,
    )


@router.post(
    "/sessions/{session_id}/messages",
    response_model=MessageResponse,
    status_code=201,
)
async def add_message(
    session_id: str,
    request: AddMessageRequest,
) -> MessageResponse:
    """添加消息到会话。"""
    service = _get_service()
    try:
        return await service.add_message(
            session_id=session_id,
            role=request.role,
            content=request.content,
            metadata=request.metadata,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")


# ─── 长期记忆 ─────────────────────────────────────────────


@router.post("/memories", response_model=MemoryEntryResponse, status_code=201)
async def create_memory(request: CreateMemoryRequest) -> MemoryEntryResponse:
    """创建长期记忆。"""
    service = _get_service()
    return await service.create_memory(
        content=request.content,
        category=request.category,
        source_session_id=request.source_session_id,
        confidence=request.confidence,
    )


@router.get("/memories", response_model=MemoryListResponse)
async def list_memories(
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MemoryListResponse:
    """列出长期记忆。"""
    service = _get_service()
    return await service.list_memories(
        category=category,
        limit=limit,
        offset=offset,
    )


@router.get("/memories/{memory_id}", response_model=MemoryEntryResponse)
async def get_memory(memory_id: str) -> MemoryEntryResponse:
    """获取长期记忆。"""
    service = _get_service()
    result = await service.get_memory(memory_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"记忆不存在: {memory_id}")
    return result


@router.put("/memories/{memory_id}", response_model=MemoryEntryResponse)
async def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
) -> MemoryEntryResponse:
    """更新长期记忆。"""
    service = _get_service()
    try:
        return await service.update_memory(
            memory_id=memory_id,
            content=request.content,
            category=request.category,
            confidence=request.confidence,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"记忆不存在: {memory_id}")


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str) -> None:
    """删除长期记忆。"""
    service = _get_service()
    deleted = await service.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"记忆不存在: {memory_id}")


# ─── 搜索 ─────────────────────────────────────────────────


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """搜索记忆和消息。"""
    service = _get_service()
    return await service.search(request)
