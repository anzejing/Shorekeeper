"""Memory Tool 定义。

提供三个工具供 Runtime 通过 Tool Calling 调用：
- read_memory: 读取长期记忆
- write_memory: 写入长期记忆
- search_memory: 搜索记忆和消息

这些工具的定义（ToolDef）注册到 Business Layer，
Runtime 只知 Tool 接口，不知 Memory 存在。
"""

from __future__ import annotations

from typing import Any

from app.runtime.models import (
    SideEffectLevel,
    TextPart,
    ToolCall,
    ToolDef,
    ToolResult,
)

# ─── Tool 定义 ────────────────────────────────────────────

READ_MEMORY_TOOL = ToolDef(
    name="read_memory",
    description=(
        "读取长期记忆列表。可按分类筛选。"
        "返回用户的偏好、事实、指令等持久化记忆。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["preference", "fact", "instruction", "other"],
                "description": "按分类筛选，不填则返回全部。",
            },
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "最大返回条数。",
            },
        },
        "required": [],
    },
    side_effect_level=SideEffectLevel.READ_ONLY,
)

WRITE_MEMORY_TOOL = ToolDef(
    name="write_memory",
    description=(
        "写入一条长期记忆。用于保存用户偏好、重要事实、特殊指令等。"
        "记忆跨会话持久化，在后续对话中自动可用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "记忆内容，简洁明确。",
            },
            "category": {
                "type": "string",
                "enum": ["preference", "fact", "instruction", "other"],
                "default": "other",
                "description": "记忆分类。",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 1.0,
                "description": "对这条记忆的置信度。",
            },
        },
        "required": ["content"],
    },
    side_effect_level=SideEffectLevel.LOCAL_MUTATION,
)

SEARCH_MEMORY_TOOL = ToolDef(
    name="search_memory",
    description=(
        "搜索记忆和历史对话。用于查找用户之前提到的信息、偏好、或历史对话内容。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词。",
            },
            "session_id": {
                "type": "string",
                "description": "限定搜索某个会话，不填则全局搜索。",
            },
            "search_type": {
                "type": "string",
                "enum": ["all", "messages", "memories"],
                "default": "all",
                "description": "搜索范围：all=全部，messages=仅消息，memories=仅长期记忆。",
            },
            "limit": {
                "type": "integer",
                "default": 10,
                "description": "最大返回条数。",
            },
        },
        "required": ["query"],
    },
    side_effect_level=SideEffectLevel.READ_ONLY,
)


# ─── Tool 列表 ────────────────────────────────────────────

MEMORY_TOOLS: list[ToolDef] = [
    READ_MEMORY_TOOL,
    WRITE_MEMORY_TOOL,
    SEARCH_MEMORY_TOOL,
]


# ─── Tool 执行器 ──────────────────────────────────────────


class MemoryToolExecutor:
    """Memory Tool 执行器。

    实现 ToolExecutor Protocol，处理 Memory 相关的工具调用。
    """

    def __init__(self, memory_service: Any) -> None:
        """初始化。

        Args:
            memory_service: MemoryService 实例。
        """
        self._service = memory_service
        self._handlers: dict[str, Any] = {
            "read_memory": self._handle_read_memory,
            "write_memory": self._handle_write_memory,
            "search_memory": self._handle_search_memory,
        }

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """执行 Memory 工具调用。"""
        handler = self._handlers.get(tool_call.tool_name)
        if handler is None:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                content=[TextPart(text=f"未知的 Memory 工具: {tool_call.tool_name}")],
                is_error=True,
            )

        try:
            return await handler(tool_call)
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                content=[TextPart(text=f"工具执行失败: {e}")],
                is_error=True,
            )

    async def _handle_read_memory(self, tool_call: ToolCall) -> ToolResult:
        """处理 read_memory 工具调用。"""
        args = tool_call.arguments
        category = args.get("category")
        limit = args.get("limit", 20)

        result = await self._service.list_memories(
            category=category,
            limit=limit,
        )

        if not result.memories:
            text = "没有找到长期记忆。"
        else:
            lines = []
            for m in result.memories:
                lines.append(f"- [{m.category}] {m.content} (置信度: {m.confidence})")
            text = f"找到 {len(result.memories)} 条记忆:\n" + "\n".join(lines)

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text=text)],
        )

    async def _handle_write_memory(self, tool_call: ToolCall) -> ToolResult:
        """处理 write_memory 工具调用。"""
        args = tool_call.arguments
        content = args.get("content", "")
        category = args.get("category", "other")
        confidence = args.get("confidence", 1.0)
        source_session_id = args.get("source_session_id")

        entry = await self._service.create_memory(
            content=content,
            category=category,
            source_session_id=source_session_id,
            confidence=confidence,
        )

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text=f"已保存记忆: {entry.content}")],
        )

    async def _handle_search_memory(self, tool_call: ToolCall) -> ToolResult:
        """处理 search_memory 工具调用。"""
        from app.memory.models import SearchRequest

        args = tool_call.arguments
        request = SearchRequest(
            query=args.get("query", ""),
            session_id=args.get("session_id"),
            search_type=args.get("search_type", "all"),
            limit=args.get("limit", 10),
        )

        result = await self._service.search(request)

        if not result.results:
            text = "没有找到匹配的结果。"
        else:
            lines = []
            for r in result.results:
                prefix = "[消息]" if r.type == "message" else "[记忆]"
                lines.append(f"{prefix} {r.content}")
            text = f"找到 {len(result.results)} 条结果:\n" + "\n".join(lines)

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text=text)],
        )
