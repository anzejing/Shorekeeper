"""MemoryStore — 长期记忆的存储接口。

长期记忆是从对话中提取的持久化信息，跨会话存在。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.memory.models import MemoryEntry


@runtime_checkable
class MemoryStore(Protocol):
    """长期记忆存储接口。"""

    async def create(
        self,
        content: str,
        category: str,
        source_session_id: str | None = None,
        confidence: float = 1.0,
    ) -> MemoryEntry:
        """创建长期记忆。

        Args:
            content: 记忆内容。
            category: 分类（preference/fact/instruction/other）。
            source_session_id: 来源会话 ID。
            confidence: 置信度 0.0 ~ 1.0。

        Returns:
            创建的 MemoryEntry。
        """
        ...  # pragma: no cover

    async def get(self, memory_id: str) -> MemoryEntry | None:
        """获取单条记忆。

        Args:
            memory_id: 记忆 ID。

        Returns:
            MemoryEntry 或 None（不存在时）。
        """
        ...  # pragma: no cover

    async def list(
        self,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryEntry], int]:
        """列出记忆，按更新时间倒序。

        Args:
            category: 按分类筛选，None 表示全部。
            limit: 最大返回数。
            offset: 偏移量。

        Returns:
            (记忆列表, 总数)。
        """
        ...  # pragma: no cover

    async def update(
        self,
        memory_id: str,
        **fields,
    ) -> MemoryEntry:
        """更新记忆字段。

        Args:
            memory_id: 记忆 ID。
            **fields: 要更新的字段（content, category, confidence）。

        Returns:
            更新后的 MemoryEntry。

        Raises:
            KeyError: 记忆不存在。
        """
        ...  # pragma: no cover

    async def delete(self, memory_id: str) -> bool:
        """删除记忆。

        Args:
            memory_id: 记忆 ID。

        Returns:
            是否成功删除（False 表示不存在）。
        """
        ...  # pragma: no cover

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """搜索长期记忆。

        使用 SQLite FTS5 全文搜索。

        Args:
            query: 搜索关键词。
            session_id: 限定来源会话，None 表示全局。
            limit: 最大返回数。

        Returns:
            匹配的 MemoryEntry 列表。
        """
        ...  # pragma: no cover
