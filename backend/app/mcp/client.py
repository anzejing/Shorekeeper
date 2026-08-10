"""MCP 客户端封装。

封装 MCP Python SDK，提供：
- 连接管理（stdio / streamable-http）
- 工具发现（list_tools）
- 工具调用（call_tool）

不负责：
- 生命周期管理（由 MCPService 负责）
- 权限审批（由 Permission 模块负责）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from app.mcp.models import MCPServerConfig, MCPTransport

log = logging.getLogger(__name__)


@asynccontextmanager
async def connect_server(config: MCPServerConfig) -> AsyncIterator[tuple[Any, Any, Any]]:
    """连接到 MCP 服务器，返回 (read_stream, write_stream, get_session_id)。

    使用 async context manager 管理连接生命周期。

    Args:
        config: 服务器配置。

    Yields:
        (read_stream, write_stream, get_session_id)

    Raises:
        ValueError: 配置无效。
        ConnectionError: 连接失败。
    """
    if config.transport == MCPTransport.STDIO:
        if not config.command:
            raise ValueError(f"MCP 服务器 '{config.name}' 缺少 command 配置")

        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env,
            cwd=config.cwd,
        )
        async with stdio_client(params) as (read, write):
            yield read, write, lambda: None

    elif config.transport == MCPTransport.STREAMABLE_HTTP:
        if not config.url:
            raise ValueError(f"MCP 服务器 '{config.name}' 缺少 url 配置")

        async with streamablehttp_client(
            url=config.url,
            headers=config.headers,
            timeout=config.timeout,
        ) as (read, write, get_session_id):
            yield read, write, get_session_id

    else:
        raise ValueError(f"不支持的传输类型: {config.transport}")


async def discover_tools(
    session: ClientSession,
) -> list[dict[str, Any]]:
    """发现 MCP 服务器上的所有工具。

    Args:
        session: 已初始化的 MCP 客户端会话。

    Returns:
        工具定义列表，每个包含 name, description, inputSchema。
    """
    result = await session.list_tools()
    tools = []
    for tool in result.tools:
        tools.append({
            "name": tool.name,
            "description": tool.description or "",
            "inputSchema": tool.inputSchema or {"type": "object", "properties": {}},
        })
    return tools


async def call_tool(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """调用 MCP 服务器上的工具。

    Args:
        session: 已初始化的 MCP 客户端会话。
        tool_name: 工具名称。
        arguments: 工具参数。

    Returns:
        调用结果，包含 content 列表和 isError 标志。
    """
    result = await session.call_tool(tool_name, arguments)

    # 转换为统一格式
    content_parts = []
    for part in result.content:
        if hasattr(part, "text"):
            content_parts.append({"type": "text", "text": part.text})
        elif hasattr(part, "data"):
            content_parts.append({
                "type": "image",
                "data": part.data,
                "mimeType": getattr(part, "mimeType", ""),
            })
        else:
            content_parts.append({"type": "text", "text": str(part)})

    return {
        "content": content_parts,
        "isError": getattr(result, "isError", False),
    }
