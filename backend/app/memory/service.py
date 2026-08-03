"""MemoryService — Memory 模块统一业务入口。

封装 SessionStore + MemoryStore 的业务逻辑。
对外提供会话管理、消息管理、长期记忆管理、搜索能力。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.memory.memory_store import MemoryStore
from app.memory.models import (
    MemoryEntry,
    MemoryEntryResponse,
    MemoryListResponse,
    MemoryCategory,
    MessageListResponse,
    MessageResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    Session,
    SessionListResponse,
    SessionResponse,
)
from app.memory.session_store import SessionStore


class MemoryService:
    """Memory 模块业务服务。

    职责：
    1. 会话生命周期管理（创建、查询、删除）
    2. 消息存储与检索
    3. 长期记忆 CRUD
    4. 跨数据源搜索
    """

    def __init__(
        self,
        session_store: SessionStore,
        memory_store: MemoryStore,
    ) -> None:
        self._session_store = session_store
        self._memory_store = memory_store

    # ─── 会话管理 ─────────────────────────────────────────

    async def create_session(
        self,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionResponse:
        """创建会话。"""
        session = await self._session_store.create_session(
            title=title,
            metadata=metadata,
        )
        return SessionResponse(
            session_id=session.session_id,
            title=session.title,
            metadata=session.metadata,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=0,
        )

    async def get_session(self, session_id: str) -> SessionResponse | None:
        """获取会话。"""
        session = await self._session_store.get_session(session_id)
        if session is None:
            return None
        count = await self._session_store.get_message_count(session_id)
        return _session_to_response(session, count)

    async def list_sessions(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> SessionListResponse:
        """列出会话。"""
        sessions, total = await self._session_store.list_sessions(limit, offset)

        # 批量获取消息数
        responses: list[SessionResponse] = []
        for s in sessions:
            count = await self._session_store.get_message_count(s.session_id)
            responses.append(_session_to_response(s, count))

        return SessionListResponse(sessions=responses, total=total)

    async def update_session(
        self,
        session_id: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionResponse:
        """更新会话。"""
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if metadata is not None:
            fields["metadata"] = metadata

        session = await self._session_store.update_session(session_id, **fields)
        count = await self._session_store.get_message_count(session_id)
        return _session_to_response(session, count)

    async def delete_session(self, session_id: str) -> bool:
        """删除会话。"""
        return await self._session_store.delete_session(session_id)

    # ─── 消息管理 ─────────────────────────────────────────

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> MessageResponse:
        """添加消息到会话。"""
        msg = await self._session_store.save_message(
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata,
        )
        return _message_to_response(msg)

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
        before: datetime | None = None,
    ) -> MessageListResponse:
        """获取会话消息。"""
        messages, total = await self._session_store.get_messages(
            session_id, limit, offset, before
        )
        return MessageListResponse(
            messages=[_message_to_response(m) for m in messages],
            total=total,
        )

    async def get_context(
        self,
        session_id: str,
        max_messages: int = 50,
        before: datetime | None = None,
    ) -> list[MessageResponse]:
        """获取会话上下文（用于 Prompt 组装）。

        返回最近 max_messages 条消息，按时间正序。
        """
        messages, _ = await self._session_store.get_messages(
            session_id, limit=max_messages, offset=0, before=before
        )
        return [_message_to_response(m) for m in messages]

    # ─── 长期记忆 ─────────────────────────────────────────

    async def create_memory(
        self,
        content: str,
        category: str = MemoryCategory.OTHER.value,
        source_session_id: str | None = None,
        confidence: float = 1.0,
    ) -> MemoryEntryResponse:
        """创建长期记忆。"""
        entry = await self._memory_store.create(
            content=content,
            category=category,
            source_session_id=source_session_id,
            confidence=confidence,
        )
        return _memory_to_response(entry)

    async def get_memory(self, memory_id: str) -> MemoryEntryResponse | None:
        """获取长期记忆。"""
        entry = await self._memory_store.get(memory_id)
        if entry is None:
            return None
        return _memory_to_response(entry)

    async def list_memories(
        self,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> MemoryListResponse:
        """列出长期记忆。"""
        entries, total = await self._memory_store.list(category, limit, offset)
        return MemoryListResponse(
            memories=[_memory_to_response(e) for e in entries],
            total=total,
        )

    async def update_memory(
        self,
        memory_id: str,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
    ) -> MemoryEntryResponse:
        """更新长期记忆。"""
        fields: dict[str, Any] = {}
        if content is not None:
            fields["content"] = content
        if category is not None:
            fields["category"] = category
        if confidence is not None:
            fields["confidence"] = confidence

        entry = await self._memory_store.update(memory_id, **fields)
        return _memory_to_response(entry)

    async def delete_memory(self, memory_id: str) -> bool:
        """删除长期记忆。"""
        return await self._memory_store.delete(memory_id)

    # ─── 搜索 ─────────────────────────────────────────────

    async def search(self, request: SearchRequest) -> SearchResponse:
        """搜索消息和长期记忆。"""
        results: list[SearchResult] = []

        # 搜索长期记忆
        if request.search_type in ("all", "memories"):
            memories = await self._memory_store.search(
                query=request.query,
                session_id=request.session_id,
                limit=request.limit,
            )
            for m in memories:
                results.append(
                    SearchResult(
                        type="memory",
                        content=m.content,
                        session_id=m.source_session_id,
                        relevance_score=m.confidence,
                        created_at=m.created_at,
                    )
                )

        # 搜索消息（通过 session 遍历，简单实现）
        if request.search_type in ("all", "messages"):
            message_results = await self._search_messages(
                query=request.query,
                session_id=request.session_id,
                limit=request.limit,
            )
            results.extend(message_results)

        # 按时间倒序排列（搜索结果默认行为）
        results.sort(key=lambda r: r.created_at, reverse=True)
        results = results[: request.limit]

        return SearchResponse(results=results, total=len(results))

    async def _search_messages(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """搜索消息内容。

        简单实现：遍历消息做关键词匹配。
        后续可引入 FTS5 或向量搜索优化。
        """
        results: list[SearchResult] = []
        query_lower = query.lower()

        if session_id:
            # 搜索指定会话
            sessions_to_search = [session_id]
        else:
            # 搜索所有会话（限制数量防止全表扫描）
            sessions, _ = await self._session_store.list_sessions(limit=50, offset=0)
            sessions_to_search = [s.session_id for s in sessions]

        for sid in sessions_to_search:
            messages, _ = await self._session_store.get_messages(
                sid, limit=200, offset=0
            )
            for msg in messages:
                if query_lower in msg.content.lower():
                    results.append(
                        SearchResult(
                            type="message",
                            content=msg.content,
                            session_id=sid,
                            relevance_score=1.0,
                            created_at=msg.created_at,
                        )
                    )
                    if len(results) >= limit:
                        return results

        return results


# ─── 转换辅助 ─────────────────────────────────────────────


def _session_to_response(session: Session, message_count: int) -> SessionResponse:
    """Session 转 SessionResponse。"""
    return SessionResponse(
        session_id=session.session_id,
        title=session.title,
        metadata=session.metadata,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=message_count,
    )


def _message_to_response(msg: Any) -> MessageResponse:
    """SessionMessage 转 MessageResponse。"""
    return MessageResponse(
        message_id=msg.message_id,
        session_id=msg.session_id,
        role=msg.role,
        content=msg.content,
        metadata=msg.metadata,
        created_at=msg.created_at,
    )


def _memory_to_response(entry: MemoryEntry) -> MemoryEntryResponse:
    """MemoryEntry 转 MemoryEntryResponse。"""
    return MemoryEntryResponse(
        memory_id=entry.memory_id,
        content=entry.content,
        category=entry.category,
        source_session_id=entry.source_session_id,
        confidence=entry.confidence,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
