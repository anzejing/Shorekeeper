"""MCP 集成测试 — L1 后端集成 + L2 数据流。

使用真实的测试 MCP 服务器（stdio 子进程）验证：
- L1: 连接/发现/注册/执行/断开
- L2: tool_search → tool_executor → MCP 全链路

需要：tests/fixtures/test_mcp_server.py 可执行
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from app.mcp.models import MCPConfig, MCPServerConfig, MCPTransport
from app.mcp.service import MCPService
from app.runtime.models import ToolCall
from app.tool.index import ToolIndex, ToolIndexEntry
from app.tool.proxy_executor import ProxyToolExecutor
from app.tool.registry import ToolRegistry
from app.tool.schema_validator import SchemaValidator
from app.tool.search import ToolSearchExecutor

# 测试 MCP 服务器路径
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_TEST_SERVER = _FIXTURES_DIR / "test_mcp_server.py"


def _srv_name(service: MCPService) -> str:
    """获取测试服务器名称（动态生成）。"""
    return list(service._servers.keys())[0]


@pytest.fixture
def venv_python() -> str:
    """venv Python 路径。"""
    return str(Path(__file__).parent.parent / ".venv" / "bin" / "python")


@pytest_asyncio.fixture
async def mcp_service(venv_python: str) -> MCPService:
    """创建并连接 MCP 服务。"""
    registry = ToolRegistry()
    index = ToolIndex()

    # 每个测试用唯一 server name 避免进程冲突
    import uuid
    server_name = f"test-mcp-{uuid.uuid4().hex[:8]}"

    config = MCPConfig(servers=[
        MCPServerConfig(
            name=server_name,
            transport=MCPTransport.STDIO,
            enabled=True,
            command=venv_python,
            args=[str(_TEST_SERVER)],
            timeout=10,
        )
    ])

    service = MCPService(config, registry, index)
    await service.initialize()

    yield service

    await service.shutdown()
    # 等待子进程完全退出
    await asyncio.sleep(0.3)


@pytest.fixture
def registry(mcp_service: MCPService) -> ToolRegistry:
    """返回已注册 MCP 工具的 ToolRegistry。"""
    # MCPService 已经注册了工具到 registry
    # 但我们还需要返回同一个 registry 实例
    return mcp_service._registry


@pytest.fixture
def index(mcp_service: MCPService) -> ToolIndex:
    """返回已注册 MCP 工具的 ToolIndex。"""
    return mcp_service._index


# ─── L1: 后端集成 ─────────────────────────────────────────


class TestL1Connection:
    """L1: MCP 服务器连接。"""

    @pytest.mark.asyncio
    async def test_server_connected(self, mcp_service: MCPService) -> None:
        """服务器应成功连接。"""
        state = mcp_service.get_server_state(_srv_name(mcp_service))
        assert state is not None
        assert state.status.value == "connected"

    @pytest.mark.asyncio
    async def test_tools_discovered(self, mcp_service: MCPService) -> None:
        """应发现 3 个测试工具。"""
        state = mcp_service.get_server_state(_srv_name(mcp_service))
        assert state is not None
        assert len(state.tools) == 3

        tool_names = {t["name"] for t in state.tools}
        assert tool_names == {"echo", "add", "greet"}


class TestL1Registration:
    """L1: 工具注册。"""

    @pytest.mark.asyncio
    async def test_registered_in_registry(self, mcp_service: MCPService) -> None:
        """MCP 工具应注册到 ToolRegistry。"""
        registry = mcp_service._registry
        assert registry.has_tool(f"{_srv_name(mcp_service)}/echo")
        assert registry.has_tool(f"{_srv_name(mcp_service)}/add")
        assert registry.has_tool(f"{_srv_name(mcp_service)}/greet")

    @pytest.mark.asyncio
    async def test_registered_in_index(self, mcp_service: MCPService) -> None:
        """MCP 工具应注册到 ToolIndex。"""
        index = mcp_service._index
        assert index.get(f"{_srv_name(mcp_service)}/echo") is not None
        assert index.get(f"{_srv_name(mcp_service)}/add") is not None
        assert index.get(f"{_srv_name(mcp_service)}/greet") is not None

    @pytest.mark.asyncio
    async def test_tool_schema_in_registry(self, mcp_service: MCPService) -> None:
        """注册的工具应包含正确的参数 schema。"""
        registry = mcp_service._registry
        echo_def = registry.get_tool(f"{_srv_name(mcp_service)}/echo")
        assert echo_def is not None
        assert "text" in echo_def.parameters.get("properties", {})

        add_def = registry.get_tool(f"{_srv_name(mcp_service)}/add")
        assert add_def is not None
        props = add_def.parameters.get("properties", {})
        assert "a" in props
        assert "b" in props
        assert props["a"]["type"] == "integer"

    @pytest.mark.asyncio
    async def test_tool_category_is_mcp(self, mcp_service: MCPService) -> None:
        """MCP 工具在 index 中的 category 应为 'mcp'。"""
        index = mcp_service._index
        entry = index.get(f"{_srv_name(mcp_service)}/echo")
        assert entry is not None
        assert entry.category == "mcp"
        assert entry.source == _srv_name(mcp_service)


class TestL1Execution:
    """L1: 工具执行。"""

    @pytest.mark.asyncio
    async def test_execute_echo(self, mcp_service: MCPService) -> None:
        """执行 echo 工具。"""
        call = ToolCall(
            tool_call_id="tc-1",
            tool_name=f"{_srv_name(mcp_service)}/echo",
            arguments={"text": "hello world"},
        )
        result = await mcp_service.execute_tool(call)
        assert result.is_error is False
        assert "hello world" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_add(self, mcp_service: MCPService) -> None:
        """执行 add 工具，验证 integer 参数。"""
        call = ToolCall(
            tool_call_id="tc-2",
            tool_name=f"{_srv_name(mcp_service)}/add",
            arguments={"a": 100, "b": 200},
        )
        result = await mcp_service.execute_tool(call)
        assert result.is_error is False
        assert "300" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_greet(self, mcp_service: MCPService) -> None:
        """执行 greet 工具。"""
        call = ToolCall(
            tool_call_id="tc-3",
            tool_name=f"{_srv_name(mcp_service)}/greet",
            arguments={"name": "Bob", "style": "casual"},
        )
        result = await mcp_service.execute_tool(call)
        assert result.is_error is False
        assert "Bob" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, mcp_service: MCPService) -> None:
        """调用不存在的工具应返回错误。"""
        call = ToolCall(
            tool_call_id="tc-4",
            tool_name=f"{_srv_name(mcp_service)}/nonexistent",
            arguments={},
        )
        result = await mcp_service.execute_tool(call)
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_execute_wrong_server(self, mcp_service: MCPService) -> None:
        """调用其他服务器的工具应返回错误。"""
        call = ToolCall(
            tool_call_id="tc-5",
            tool_name="other-server/echo",
            arguments={"text": "test"},
        )
        result = await mcp_service.execute_tool(call)
        assert result.is_error is True


class TestL1Disconnect:
    """L1: 断开连接。"""

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self, venv_python: str) -> None:
        """断开后工具应从 registry 和 index 清理。"""
        registry = ToolRegistry()
        index = ToolIndex()
        srv_name = f"temp-mcp-{uuid.uuid4().hex[:8]}"
        config = MCPConfig(servers=[
            MCPServerConfig(
                name=srv_name,
                transport=MCPTransport.STDIO,
                enabled=True,
                command=venv_python,
                args=[str(_TEST_SERVER)],
                timeout=10,
            )
        ])

        service = MCPService(config, registry, index)
        await service.initialize()

        # 确认工具已注册
        assert registry.has_tool(f"{srv_name}/echo")
        assert index.get(f"{srv_name}/echo") is not None

        # 断开
        await service.remove_server(srv_name)
        await asyncio.sleep(0.3)

        # 确认工具已清理
        assert not registry.has_tool(f"{srv_name}/echo")
        assert index.get(f"{srv_name}/echo") is None


# ─── L2: 数据流 ──────────────────────────────────────────


class TestL2ToolSearch:
    """L2: tool_search 搜索 MCP 工具。"""

    @pytest.mark.asyncio
    async def test_search_finds_mcp_tools(self, mcp_service: MCPService) -> None:
        """tool_search 应能找到 MCP 工具。"""
        index = mcp_service._index
        search_executor = ToolSearchExecutor(index)

        call = ToolCall(
            tool_call_id="tc-s1",
            tool_name="tool_search",
            arguments={"query": "echo"},
        )
        result = await search_executor.execute(call)
        assert result.is_error is False
        assert f"{_srv_name(mcp_service)}/echo" in result.content[0].text

    @pytest.mark.asyncio
    async def test_search_returns_full_schema(self, mcp_service: MCPService) -> None:
        """搜索结果应包含完整参数定义。"""
        index = mcp_service._index
        search_executor = ToolSearchExecutor(index)

        call = ToolCall(
            tool_call_id="tc-s2",
            tool_name="tool_search",
            arguments={"query": "add 计算"},
        )
        result = await search_executor.execute(call)
        text = result.content[0].text
        assert f"{_srv_name(mcp_service)}/add" in text
        assert "a" in text
        assert "b" in text
        assert "integer" in text
        assert "必填" in text

    @pytest.mark.asyncio
    async def test_search_by_category(self, mcp_service: MCPService) -> None:
        """按 category=mcp 搜索应只返回 MCP 工具。"""
        index = mcp_service._index
        # 添加一个 core 工具到 index
        index.add(ToolIndexEntry(
            name="bash_execute",
            description="执行 shell 命令",
            parameters={},
            category="core",
            source="builtin",
        ))

        search_executor = ToolSearchExecutor(index)
        # 搜索 echo（两个 category 都有匹配）
        call = ToolCall(
            tool_call_id="tc-s3",
            tool_name="tool_search",
            arguments={"query": "echo", "category": "mcp"},
        )
        result = await search_executor.execute(call)
        text = result.content[0].text
        assert _srv_name(mcp_service) in text
        assert "bash_execute" not in text


class TestL2ToolExecutor:
    """L2: tool_executor 调用 MCP 工具。"""

    @pytest.mark.asyncio
    async def test_executor_routes_to_mcp(self, mcp_service: MCPService) -> None:
        """tool_executor 应正确路由到 MCP 服务器。"""
        registry = mcp_service._registry
        validator = SchemaValidator()
        proxy = ProxyToolExecutor(registry, validator)

        call = ToolCall(
            tool_call_id="tc-e1",
            tool_name="tool_executor",
            arguments={
                "tool_name": f"{_srv_name(mcp_service)}/echo",
                "arguments": {"text": "via executor"},
            },
        )
        result = await proxy.execute(call)
        assert result.is_error is False
        assert "via executor" in result.content[0].text

    @pytest.mark.asyncio
    async def test_executor_validates_params(self, mcp_service: MCPService) -> None:
        """tool_executor 应校验参数并返回详细错误。"""
        registry = mcp_service._registry
        validator = SchemaValidator()
        proxy = ProxyToolExecutor(registry, validator)

        # 缺少必填参数 text
        call = ToolCall(
            tool_call_id="tc-e2",
            tool_name="tool_executor",
            arguments={
                "tool_name": f"{_srv_name(mcp_service)}/echo",
                "arguments": {},
            },
        )
        result = await proxy.execute(call)
        assert result.is_error is True
        text = result.content[0].text
        assert "参数校验失败" in text
        assert "text" in text
        assert "必填" in text

    @pytest.mark.asyncio
    async def test_executor_type_error(self, mcp_service: MCPService) -> None:
        """参数类型错误时应返回类型错误信息。"""
        registry = mcp_service._registry
        validator = SchemaValidator()
        proxy = ProxyToolExecutor(registry, validator)

        # a 应为 integer，传 string
        call = ToolCall(
            tool_call_id="tc-e3",
            tool_name="tool_executor",
            arguments={
                "tool_name": f"{_srv_name(mcp_service)}/add",
                "arguments": {"a": "not a number", "b": 2},
            },
        )
        result = await proxy.execute(call)
        assert result.is_error is True
        assert "类型错误" in result.content[0].text



