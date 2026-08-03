"""Memory 模块领域模型。

定义会话、会话消息、长期记忆的数据结构。
标识符使用 str（UUID），与 Runtime 保持一致。
核心模型使用 dataclass；API 请求/响应用 Pydantic。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── 标识符 ───────────────────────────────────────────────


def new_session_id() -> str:
    """生成唯一 Session ID。"""
    return str(uuid.uuid4())


def new_message_id() -> str:
    """生成唯一消息 ID。"""
    return str(uuid.uuid4())


def new_memory_id() -> str:
    """生成唯一记忆 ID。"""
    return str(uuid.uuid4())


# ─── 枚举 ─────────────────────────────────────────────────


class MessageRole(str, Enum):
    """消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class MemoryCategory(str, Enum):
    """长期记忆分类。"""

    PREFERENCE = "preference"      # 用户偏好
    FACT = "fact"                  # 事实信息
    INSTRUCTION = "instruction"    # 用户指令
    OTHER = "other"                # 其他


# ─── 领域模型 ──────────────────────────────────────────────


@dataclass
class Session:
    """会话——一组关联的对话。"""

    session_id: str
    title: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass
class SessionMessage:
    """会话级消息。

    区别于 Runtime 的 Run 内消息。Session 消息是跨 Run 的完整对话记录。
    """

    message_id: str
    session_id: str
    role: str                # MessageRole 值
    content: str
    metadata: dict[str, Any]
    created_at: datetime


@dataclass
class MemoryEntry:
    """长期记忆条目。"""

    memory_id: str
    content: str
    category: str            # MemoryCategory 值
    source_session_id: str | None
    confidence: float        # 0.0 ~ 1.0
    created_at: datetime
    updated_at: datetime


# ─── Pydantic 模型（API 请求/响应）─────────────────────────


class CreateSessionRequest(BaseModel):
    """创建会话请求。"""

    title: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """会话响应。"""

    session_id: str
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class SessionListResponse(BaseModel):
    """会话列表响应。"""

    sessions: list[SessionResponse]
    total: int


class AddMessageRequest(BaseModel):
    """添加消息请求。"""

    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageResponse(BaseModel):
    """消息响应。"""

    message_id: str
    session_id: str
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MessageListResponse(BaseModel):
    """消息列表响应。"""

    messages: list[MessageResponse]
    total: int


class CreateMemoryRequest(BaseModel):
    """创建长期记忆请求。"""

    content: str
    category: str = MemoryCategory.OTHER.value
    source_session_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class UpdateMemoryRequest(BaseModel):
    """更新长期记忆请求。"""

    content: str | None = None
    category: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class MemoryEntryResponse(BaseModel):
    """长期记忆响应。"""

    memory_id: str
    content: str
    category: str
    source_session_id: str | None = None
    confidence: float
    created_at: datetime
    updated_at: datetime


class MemoryListResponse(BaseModel):
    """长期记忆列表响应。"""

    memories: list[MemoryEntryResponse]
    total: int


class SearchRequest(BaseModel):
    """搜索请求。"""

    query: str
    session_id: str | None = None
    search_type: str = Field(default="all", pattern="^(all|messages|memories)$")
    limit: int = Field(default=20, ge=1, le=100)


class SearchResult(BaseModel):
    """搜索结果项。"""

    type: str                # message | memory
    content: str
    session_id: str | None = None
    relevance_score: float = 0.0
    created_at: datetime


class SearchResponse(BaseModel):
    """搜索响应。"""

    results: list[SearchResult]
    total: int
