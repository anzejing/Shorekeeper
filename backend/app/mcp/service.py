"""MCPService — MCP 服务器生命周期管理。

职责：
1. 管理多个 MCP 服务器的连接/断开/重连
2. 发现工具并注册到 ToolRegistry + ToolIndex
3. 提供工具执行路由（MCP tool call → MCP 服务器）
4. 配置持久化

不负责：
- 权限审批（由 Permission 模块负责）
- Agent Loop（由 Runtime 负责）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp import ClientSession

from app.mcp.client import call_tool, connect_server, discover_tools
from app.mcp.models import (
    MCPConfig,
    MCPServerConfig,
    MCPServerState,
    MCPServerStatus,
    MCPTransport,
)
from app.runtime.models import (
    SideEffectLevel,
    TextPart,
    ToolCall,
    ToolDef,
    ToolResult,
)
from app.tool.index import ToolIndex, ToolIndexEntry
from app.tool.registry import ToolRegistry

log = logging.getLogger(__name__)


class MCPService:
    """MCP 服务器管理服务。

    管理 MCP 服务器的完整生命周期：
    - 启动时连接所有启用的服务器
    - 发现工具并注册到 ToolRegistry + ToolIndex
    - 处理工具调用路由
    - 断开连接时清理注册
    """

    def __init__(
        self,
        config: MCPConfig,
        registry: ToolRegistry,
        index: ToolIndex,
    ) -> None:
        self._config = config
        self._registry = registry
        self._index = index
        # server_name → MCPServerState
        self._servers: dict[str, MCPServerState] = {}
        # server_name → (read_stream, write_stream, session_task)
        self._connections: dict[str, tuple[Any, Any, asyncio.Task]] = {}
        # mcp_server/tool_name → server_name（用于路由）
        self._tool_routing: dict[str, str] = {}

    async def initialize(self) -> None:
        """启动时连接所有启用的 MCP 服务器。"""
        for server_config in self._config.servers:
            if not server_config.enabled:
                log.info("MCP 服务器 '%s' 已禁用，跳过", server_config.name)
                continue

            state = MCPServerState(config=server_config)
            self._servers[server_config.name] = state

            try:
                await self._connect_server(server_config.name)
            except Exception as e:
                log.error(
                    "MCP 服务器 '%s' 连接失败: %s",
                    server_config.name, e,
                )
                state.status = MCPServerStatus.ERROR
                state.error = str(e)

    async def shutdown(self) -> None:
        """关闭所有 MCP 服务器连接。"""
        for name in list(self._connections.keys()):
            await self._disconnect_server(name)
        log.info("MCP 服务已关闭")

    # ─── 服务器管理 ───────────────────────────────────────

    async def add_server(self, config: MCPServerConfig) -> None:
        """动态添加并连接一个 MCP 服务器。"""
        if config.name in self._servers:
            raise ValueError(f"MCP 服务器 '{config.name}' 已存在")

        state = MCPServerState(config=config)
        self._servers[config.name] = state
        self._config.servers.append(config)

        if config.enabled:
            await self._connect_server(config.name)

    async def remove_server(self, name: str) -> None:
        """移除一个 MCP 服务器（断开连接 + 清理注册）。"""
        if name not in self._servers:
            raise ValueError(f"MCP 服务器 '{name}' 不存在")

        await self._disconnect_server(name)
        del self._servers[name]
        self._config.servers = [
            s for s in self._config.servers if s.name != name
        ]

    async def reconnect_server(self, name: str) -> None:
        """重连指定服务器。"""
        if name not in self._servers:
            raise ValueError(f"MCP 服务器 '{name}' 不存在")

        await self._disconnect_server(name)
        await self._connect_server(name)

    def get_server_state(self, name: str) -> MCPServerState | None:
        """获取服务器状态。"""
        return self._servers.get(name)

    def list_servers(self) -> list[MCPServerState]:
        """列出所有服务器状态。"""
        return list(self._servers.values())

    # ─── 工具执行（供 ProxyToolExecutor 路由）────────────

    async def execute_tool(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """执行 MCP 工具调用。

        由 MCPToolExecutor 调用，路由到正确的 MCP 服务器。
        """
        server_name = self._tool_routing.get(tool_call.tool_name)
        if server_name is None:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                content=[TextPart(text=f"未知的 MCP 工具: {tool_call.tool_name}")],
                is_error=True,
            )

        state = self._servers.get(server_name)
        if state is None or state.session is None:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                content=[TextPart(text=f"MCP 服务器 '{server_name}' 未连接")],
                is_error=True,
            )

        # 提取原始工具名（去掉 server/ 前缀）
        # 注册时用 server_name/tool_name，MCP 调用时用原始 tool_name
        mcp_tool_name = tool_call.tool_name
        if "/" in mcp_tool_name:
            mcp_tool_name = mcp_tool_name.split("/", 1)[1]

        try:
            result = await call_tool(
                state.session, mcp_tool_name, tool_call.arguments
            )

            content_parts = []
            for part in result.get("content", []):
                if part.get("type") == "text":
                    content_parts.append(TextPart(text=part["text"]))
                else:
                    content_parts.append(TextPart(text=str(part)))

            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                content=content_parts,
                is_error=result.get("isError", False),
            )

        except Exception as e:
            log.exception("MCP 工具 '%s' 执行失败", tool_call.tool_name)
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                content=[TextPart(text=f"MCP 工具执行失败: {e}")],
                is_error=True,
            )

    # ─── 内部方法 ─────────────────────────────────────────

    async def _connect_server(self, name: str) -> None:
        """连接到指定 MCP 服务器并注册工具。

        启动一个后台任务维持长连接。
        任务内部：连接 → 初始化 → 发现工具 → 注册 → 保持存活。
        """
        state = self._servers[name]
        config = state.config

        state.status = MCPServerStatus.CONNECTING
        log.info("正在连接 MCP 服务器 '%s' (%s)...", name, config.transport.value)

        # 启动后台连接任务
        task = asyncio.create_task(
            self._connection_loop(name),
            name=f"mcp-{name}",
        )
        self._connections[name] = (None, None, task)

        # 等待连接建立或失败（最多 timeout 秒）
        timeout = config.timeout
        try:
            await asyncio.wait_for(
                self._wait_connected(name), timeout=timeout
            )
        except asyncio.TimeoutError:
            task.cancel()
            state.status = MCPServerStatus.ERROR
            state.error = f"连接超时 ({timeout}s)"
            raise ConnectionError(state.error)

    async def _connection_loop(self, name: str) -> None:
        """MCP 服务器长连接任务。

        维持连接直到被取消。
        """
        state = self._servers[name]
        config = state.config

        try:
            async with connect_server(config) as (read_stream, write_stream, get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    state.session = session
                    state.error = None

                    # 先发现并注册工具，再标记 CONNECTED
                    tools = await discover_tools(session)
                    state.tools = tools
                    self._register_tools(name, tools, config)

                    # 所有准备工作完成，标记为已连接
                    state.status = MCPServerStatus.CONNECTED

                    log.info(
                        "MCP 服务器 '%s' 已连接，发现 %d 个工具",
                        name, len(tools),
                    )

                    # 保持连接，直到被取消
                    try:
                        await asyncio.Event().wait()  # 永久等待
                    except asyncio.CancelledError:
                        pass

        except asyncio.CancelledError:
            raise
        except Exception as e:
            state.status = MCPServerStatus.ERROR
            state.error = str(e)
            log.error("MCP 服务器 '%s' 连接异常: %s", name, e)

    async def _wait_connected(self, name: str) -> None:
        """等待服务器进入 CONNECTED 或 ERROR 状态。"""
        state = self._servers[name]
        while state.status in (MCPServerStatus.CONNECTING, MCPServerStatus.DISCONNECTED):
            await asyncio.sleep(0.1)
        if state.status == MCPServerStatus.ERROR:
            raise ConnectionError(state.error or "连接失败")

    async def _disconnect_server(self, name: str) -> None:
        """断开 MCP 服务器并清理注册。"""
        state = self._servers.get(name)
        if state is None:
            return

        # 取消连接任务
        conn = self._connections.pop(name, None)
        if conn and conn[2] is not None:
            conn[2].cancel()
            try:
                await conn[2]
            except asyncio.CancelledError:
                pass

        # 清理注册的工具
        self._unregister_tools(name)

        state.status = MCPServerStatus.DISCONNECTED
        state.session = None
        state.tools = []

        log.info("MCP 服务器 '%s' 已断开", name)

    def _register_tools(
        self,
        server_name: str,
        tools: list[dict[str, Any]],
        config: MCPServerConfig,
    ) -> None:
        """将 MCP 工具注册到 ToolRegistry 和 ToolIndex。"""
        for tool_def in tools:
            # 命名空间：server_name/tool_name
            full_name = f"{server_name}/{tool_def['name']}"

            # 注册到 ToolRegistry
            td = ToolDef(
                name=full_name,
                description=tool_def["description"],
                parameters=tool_def["inputSchema"],
                side_effect_level=SideEffectLevel.EXTERNAL_MUTATION,
            )
            # 用 MCPToolExecutor 作为执行器
            executor = MCPToolExecutorProxy(self, full_name)
            self._registry.register(td, executor)

            # 注册到 ToolIndex
            self._index.add(ToolIndexEntry(
                name=full_name,
                description=tool_def["description"],
                parameters=tool_def["inputSchema"],
                category="mcp",
                source=server_name,
                tags=[server_name, "mcp"],
            ))

            # 记录路由
            self._tool_routing[full_name] = server_name

        log.info(
            "MCP 服务器 '%s': 注册 %d 个工具到 Registry 和 Index",
            server_name, len(tools),
        )

    def _unregister_tools(self, server_name: str) -> None:
        """清理指定服务器注册的所有工具。"""
        to_remove = [
            name for name, srv in self._tool_routing.items()
            if srv == server_name
        ]
        for tool_name in to_remove:
            self._registry.unregister(tool_name)
            self._index.remove(tool_name)
            del self._tool_routing[tool_name]

        if to_remove:
            log.info(
                "MCP 服务器 '%s': 清理 %d 个工具",
                server_name, len(to_remove),
            )


class MCPToolExecutorProxy:
    """MCP 工具执行代理。

    注册到 ToolRegistry 的执行器，将调用路由到 MCPService.execute_tool。
    因为 ToolRegistry 要求每个工具配一个执行器，
    我们用这个代理类统一处理所有 MCP 工具调用。
    """

    def __init__(self, service: MCPService, tool_name: str) -> None:
        self._service = service
        self._tool_name = tool_name

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        return await self._service.execute_tool(
            tool_call, cancellation=cancellation, context=context,
        )
