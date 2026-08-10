"""MCPService 测试。

使用 mock 避免实际网络/进程依赖。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.models import (
    MCPConfig,
    MCPServerConfig,
    MCPServerStatus,
    MCPTransport,
)
from app.mcp.service import MCPService, MCPToolExecutorProxy
from app.runtime.models import ToolCall
from app.tool.index import ToolIndex
from app.tool.registry import ToolRegistry


# ─── 辅助 ─────────────────────────────────────────────────


def _make_config(name: str = "test-server", enabled: bool = True) -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        transport=MCPTransport.STDIO,
        enabled=enabled,
        command="echo",
        args=["hello"],
    )


def _make_mcp_config(servers: list[MCPServerConfig] | None = None) -> MCPConfig:
    return MCPConfig(servers=servers or [])


# ─── 配置模型测试 ─────────────────────────────────────────


class TestMCPServerConfig:
    def test_defaults(self) -> None:
        config = MCPServerConfig(name="test")
        assert config.transport == MCPTransport.STDIO
        assert config.enabled is True
        assert config.command == ""
        assert config.args == []
        assert config.timeout == 30.0
        assert config.auto_approve == []

    def test_stdio_config(self) -> None:
        config = MCPServerConfig(
            name="fs",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
        )
        assert config.transport == MCPTransport.STDIO
        assert config.command == "npx"

    def test_http_config(self) -> None:
        config = MCPServerConfig(
            name="remote",
            transport=MCPTransport.STREAMABLE_HTTP,
            url="http://localhost:3001/mcp",
        )
        assert config.transport == MCPTransport.STREAMABLE_HTTP
        assert config.url == "http://localhost:3001/mcp"


class TestMCPConfig:
    def test_empty(self) -> None:
        config = MCPConfig()
        assert config.servers == []

    def test_with_servers(self) -> None:
        config = MCPConfig(servers=[
            MCPServerConfig(name="a"),
            MCPServerConfig(name="b"),
        ])
        assert len(config.servers) == 2


# ─── MCPService 基础测试 ─────────────────────────────────


class TestMCPServiceInit:
    def test_init_empty(self) -> None:
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()

        service = MCPService(config, registry, index)

        assert service.list_servers() == []

    def test_init_with_disabled_server(self) -> None:
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config([
            _make_config("disabled-server", enabled=False),
        ])

        service = MCPService(config, registry, index)
        # disabled 服务器不应被加入 _servers
        assert service.get_server_state("disabled-server") is None


class TestMCPServiceToolRouting:
    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self) -> None:
        """调用未注册的 MCP 工具应返回错误。"""
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()
        service = MCPService(config, registry, index)

        call = ToolCall(
            tool_call_id="tc-1",
            tool_name="unknown-server/unknown-tool",
            arguments={},
        )

        result = await service.execute_tool(call)

        assert result.is_error is True
        assert "未知" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_disconnected_server(self) -> None:
        """调用已断开的服务器工具应返回错误。"""
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()
        service = MCPService(config, registry, index)

        # 手动注册一个路由但不连接服务器
        service._tool_routing["test/tool"] = "test"
        service._servers["test"] = MagicMock(
            session=None,
            status=MCPServerStatus.DISCONNECTED,
        )

        call = ToolCall(
            tool_call_id="tc-1",
            tool_name="test/tool",
            arguments={},
        )

        result = await service.execute_tool(call)

        assert result.is_error is True
        assert "未连接" in result.content[0].text


# ─── MCPToolExecutorProxy 测试 ───────────────────────────


class TestMCPToolExecutorProxy:
    @pytest.mark.asyncio
    async def test_proxy_delegates_to_service(self) -> None:
        """代理应将调用转发到 MCPService.execute_tool。"""
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()
        service = MCPService(config, registry, index)

        proxy = MCPToolExecutorProxy(service, "test/tool")

        # mock execute_tool
        service.execute_tool = AsyncMock(return_value=MagicMock(is_error=False))

        call = ToolCall(
            tool_call_id="tc-1",
            tool_name="test/tool",
            arguments={"key": "value"},
        )

        await proxy.execute(call, cancellation=None)

        service.execute_tool.assert_called_once()


# ─── 工具注册测试 ─────────────────────────────────────────


class TestToolRegistration:
    def test_register_tools(self) -> None:
        """_register_tools 应将工具注册到 registry 和 index。"""
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()
        service = MCPService(config, registry, index)

        tools = [
            {"name": "read", "description": "读取", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "write", "description": "写入", "inputSchema": {"type": "object", "properties": {}}},
        ]

        service._register_tools("my-server", tools, _make_config("my-server"))

        # 验证 registry
        assert registry.has_tool("my-server/read")
        assert registry.has_tool("my-server/write")

        # 验证 index
        assert index.get("my-server/read") is not None
        assert index.get("my-server/write") is not None

        # 验证路由
        assert service._tool_routing["my-server/read"] == "my-server"
        assert service._tool_routing["my-server/write"] == "my-server"

    def test_unregister_tools(self) -> None:
        """_unregister_tools 应清理指定服务器的所有工具。"""
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()
        service = MCPService(config, registry, index)

        tools = [
            {"name": "a", "description": "A", "inputSchema": {}},
            {"name": "b", "description": "B", "inputSchema": {}},
        ]
        service._register_tools("srv", tools, _make_config("srv"))

        assert registry.has_tool("srv/a")
        service._unregister_tools("srv")

        assert not registry.has_tool("srv/a")
        assert not registry.has_tool("srv/b")
        assert index.get("srv/a") is None


# ─── 添加/移除服务器测试 ─────────────────────────────────


class TestServerManagement:
    @pytest.mark.asyncio
    async def test_add_server(self) -> None:
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()
        service = MCPService(config, registry, index)

        new_config = _make_config("new-server")
        # mock _connect_server 避免实际连接
        service._connect_server = AsyncMock()

        await service.add_server(new_config)

        assert service.get_server_state("new-server") is not None
        assert len(service.list_servers()) == 1
        service._connect_server.assert_called_once_with("new-server")

    @pytest.mark.asyncio
    async def test_add_duplicate_server_raises(self) -> None:
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()
        service = MCPService(config, registry, index)
        service._servers["dup"] = MagicMock()

        with pytest.raises(ValueError, match="已存在"):
            await service.add_server(_make_config("dup"))

    @pytest.mark.asyncio
    async def test_remove_server(self) -> None:
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()
        service = MCPService(config, registry, index)
        service._servers["to-remove"] = MagicMock()
        service._disconnect_server = AsyncMock()

        await service.remove_server("to-remove")

        assert service.get_server_state("to-remove") is None
        service._disconnect_server.assert_called_once_with("to-remove")

    @pytest.mark.asyncio
    async def test_remove_nonexistent_raises(self) -> None:
        registry = ToolRegistry()
        index = ToolIndex()
        config = _make_mcp_config()
        service = MCPService(config, registry, index)

        with pytest.raises(ValueError, match="不存在"):
            await service.remove_server("nonexistent")
