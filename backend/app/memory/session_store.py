"""SessionStore — 会话与会话消息的存储接口。

会话是跨 Run 的对话容器。一个 Session 包含多条消息，跨越多个 Run。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.memory.models import Session, SessionMessage


@runtime_checkable
class SessionStore(Protocol):
    """会话存储接口。"""

    async def create_session(
        self,
        title: str,
        metadata: dict | None = None,
    ) -> Session:
        """创建新会话。

        Args:
            title: 会话标题，空字符串表示自动生成。
            metadata: 扩展字段。

        Returns:
            创建的 Session。
        """
        ...  # pragma: no cover

    async def get_session(self, session_id: str) -> Session | None:
        """获取会话。

        Args:
            session_id: 会话 ID。

        Returns:
            Session 或 None（不存在时）。
        """
        ...  # pragma: no cover

    async def list_sessions(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Session], int]:
        """列出会话，按更新时间倒序。

        Args:
            limit: 最大返回数。
            offset: 偏移量。

        Returns:
            (会话列表, 总数)。
        """
        ...  # pragma: no cover

    async def update_session(
        self,
        session_id: str,
        **fields,
    ) -> Session:
        """更新会话字段。

        Args:
            session_id: 会话 ID。
            **fields: 要更新的字段（title, metadata）。

        Returns:
            更新后的 Session。

        Raises:
            KeyError: 会话不存在。
        """
        ...  # pragma: no cover

    async def delete_session(self, session_id: str) -> bool:
        """删除会话及其所有消息。

        Args:
            session_id: 会话 ID。

        Returns:
            是否成功删除（False 表示不存在）。
        """
        ...  # pragma: no cover

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> SessionMessage:
        """保存消息到会话。

        自动更新会话的 updated_at。

        Args:
            session_id: 会话 ID。
            role: 消息角色（user/assistant/system/tool）。
            content: 消息内容。
            metadata: 扩展字段。

        Returns:
            保存的 SessionMessage。

        Raises:
            KeyError: 会话不存在。
        """
        ...  # pragma: no cover

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
        before: datetime | None = None,
    ) -> tuple[list[SessionMessage], int]:
        """获取会话消息，按时间正序。

        Args:
            session_id: 会话 ID。
            limit: 最大返回数。
            offset: 偏移量。
            before: 只返回此时间之前的消息。

        Returns:
            (消息列表, 总数)。
        """
        ...  # pragma: no cover

    async def get_message_count(self, session_id: str) -> int:
        """获取会话的消息总数。

        Args:
            session_id: 会话 ID。

        Returns:
            消息数量。
        """
        ...  # pragma: no cover
