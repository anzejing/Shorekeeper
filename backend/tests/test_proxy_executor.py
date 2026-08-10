"""ProxyToolExecutor 测试。"""

from __future__ import annotations

import pytest

from app.runtime.models import (
    SideEffectLevel,
    TextPart,
    ToolCall,
    ToolDef,
    ToolResult,
)
from app.tool.proxy_executor import ProxyToolExecutor
from app.tool.registry import ToolRegistry
from app.tool.schema_validator import SchemaValidator


# ─── 辅助 ─────────────────────────────────────────────────


def _make_registry_with_tools() -> tuple[ToolRegistry, "MockExecutor"]:
    """创建包含几个测试工具的 registry。"""
    registry = ToolRegistry()
    executor = MockExecutor()

    registry.register(
        ToolDef(
            name="bash_execute",
            description="执行 shell 命令",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "命令"},
                },
                "required": ["command"],
            },
            side_effect_level=SideEffectLevel.EXTERNAL_MUTATION,
        ),
        executor,
    )
    registry.register(
        ToolDef(
            name="read_file",
            description="读取文件",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "路径"},
                },
                "required": ["path"],
            },
            side_effect_level=SideEffectLevel.READ_ONLY,
        ),
        executor,
    )
    # 注册 tool_search 和 tool_executor（模拟实际注册）
    registry.register(
        ToolDef(
            name="tool_search",
            description="搜索工具",
            parameters={},
            side_effect_level=SideEffectLevel.READ_ONLY,
        ),
        executor,
    )
    registry.register(
        ToolDef(
            name="tool_executor",
            description="代理执行",
            parameters={},
            side_effect_level=SideEffectLevel.EXTERNAL_MUTATION,
        ),
        executor,
    )

    return registry, executor


class MockExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def execute(self, tool_call: ToolCall, *, cancellation=None, context=None) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text=f"executed: {tool_call.tool_name}")],
        )


@pytest.fixture
def setup():
    registry, executor = _make_registry_with_tools()
    validator = SchemaValidator()
    proxy = ProxyToolExecutor(registry, validator)
    return proxy, executor, registry


def _proxy_call(tool_name: str, arguments: dict) -> ToolCall:
    return ToolCall(
        tool_call_id="tc-proxy",
        tool_name="tool_executor",
        arguments={"tool_name": tool_name, "arguments": arguments},
    )


# ─── 正常路由 ─────────────────────────────────────────────


class TestRouting:
    @pytest.mark.asyncio
    async def test_route_to_bash(self, setup) -> None:
        proxy, executor, _ = setup
        call = _proxy_call("bash_execute", {"command": "echo hello"})
        result = await proxy.execute(call)

        assert result.is_error is False
        assert "executed: bash_execute" in result.content[0].text
        assert len(executor.calls) == 1
        assert executor.calls[0].tool_name == "bash_execute"
        assert executor.calls[0].arguments == {"command": "echo hello"}

    @pytest.mark.asyncio
    async def test_route_to_read_file(self, setup) -> None:
        proxy, executor, _ = setup
        call = _proxy_call("read_file", {"path": "/tmp/test.txt"})
        result = await proxy.execute(call)

        assert result.is_error is False
        assert len(executor.calls) == 1
        assert executor.calls[0].tool_name == "read_file"


# ─── 参数校验 ─────────────────────────────────────────────


class TestValidation:
    @pytest.mark.asyncio
    async def test_missing_required(self, setup) -> None:
        proxy, executor, _ = setup
        call = _proxy_call("bash_execute", {})  # 缺少 command
        result = await proxy.execute(call)

        assert result.is_error is True
        assert "参数校验失败" in result.content[0].text
        assert "command" in result.content[0].text
        assert len(executor.calls) == 0  # 未执行

    @pytest.mark.asyncio
    async def test_wrong_type(self, setup) -> None:
        proxy, executor, _ = setup
        call = _proxy_call("bash_execute", {"command": 123})  # 应为 string
        result = await proxy.execute(call)

        assert result.is_error is True
        assert "类型错误" in result.content[0].text
        assert len(executor.calls) == 0

    @pytest.mark.asyncio
    async def test_unknown_param_warning(self, setup) -> None:
        """未知参数产生警告但不阻止执行。"""
        proxy, executor, _ = setup
        call = _proxy_call("bash_execute", {"command": "ls", "extra": "val"})
        result = await proxy.execute(call)

        assert result.is_error is False
        assert "注意" in result.content[0].text
        assert len(executor.calls) == 1

    @pytest.mark.asyncio
    async def test_error_includes_param_definition(self, setup) -> None:
        """错误消息应包含参数定义，帮助 LLM 修正。"""
        proxy, _, _ = setup
        call = _proxy_call("bash_execute", {})
        result = await proxy.execute(call)
        text = result.content[0].text

        assert "参数定义" in text
        assert "command" in text
        assert "string" in text

    @pytest.mark.asyncio
    async def test_error_includes_provided_args(self, setup) -> None:
        """错误消息应显示 LLM 提供的参数。"""
        proxy, _, _ = setup
        call = _proxy_call("bash_execute", {"wrong": "value"})
        result = await proxy.execute(call)
        text = result.content[0].text

        assert "你提供的参数" in text


# ─── 工具不存在 ────────────────────────────────────────────


class TestNotFound:
    @pytest.mark.asyncio
    async def test_tool_not_found(self, setup) -> None:
        proxy, executor, _ = setup
        call = _proxy_call("nonexistent_tool", {"x": 1})
        result = await proxy.execute(call)

        assert result.is_error is True
        assert "不存在" in result.content[0].text
        assert "tool_search" in result.content[0].text
        assert len(executor.calls) == 0

    @pytest.mark.asyncio
    async def test_not_found_suggests_available_tools(self, setup) -> None:
        """工具不存在时应提示可用工具。"""
        proxy, _, _ = setup
        call = _proxy_call("nonexistent", {})
        result = await proxy.execute(call)
        text = result.content[0].text

        assert "bash_execute" in text or "read_file" in text


# ─── 禁止调用 ────────────────────────────────────────────


class TestBlocked:
    @pytest.mark.asyncio
    async def test_cannot_call_self(self, setup) -> None:
        proxy, executor, _ = setup
        call = _proxy_call("tool_executor", {})
        result = await proxy.execute(call)

        assert result.is_error is True
        assert "不允许" in result.content[0].text
        assert len(executor.calls) == 0

    @pytest.mark.asyncio
    async def test_cannot_call_tool_search(self, setup) -> None:
        proxy, executor, _ = setup
        call = _proxy_call("tool_search", {"query": "test"})
        result = await proxy.execute(call)

        assert result.is_error is True
        assert "不允许" in result.content[0].text
        assert len(executor.calls) == 0


# ─── 缺少参数 ────────────────────────────────────────────


class TestMissingArgs:
    @pytest.mark.asyncio
    async def test_missing_tool_name(self, setup) -> None:
        proxy, executor, _ = setup
        call = ToolCall(
            tool_call_id="tc-1",
            tool_name="tool_executor",
            arguments={"arguments": {}},
        )
        result = await proxy.execute(call)

        assert result.is_error is True
        assert "tool_name" in result.content[0].text
        assert len(executor.calls) == 0

    @pytest.mark.asyncio
    async def test_arguments_not_object(self, setup) -> None:
        proxy, executor, _ = setup
        call = ToolCall(
            tool_call_id="tc-1",
            tool_name="tool_executor",
            arguments={"tool_name": "bash_execute", "arguments": "not a dict"},
        )
        result = await proxy.execute(call)

        assert result.is_error is True
        assert "对象" in result.content[0].text
        assert len(executor.calls) == 0


# ─── 错误消息格式 ─────────────────────────────────────────


class TestErrorMessageFormat:
    @pytest.mark.asyncio
    async def test_error_has_fix_hint(self, setup) -> None:
        """错误消息应包含修正建议。"""
        proxy, _, _ = setup
        call = _proxy_call("bash_execute", {})
        result = await proxy.execute(call)
        text = result.content[0].text

        assert "修正建议" in text or "提示" in text

    @pytest.mark.asyncio
    async def test_error_mentions_tool_search(self, setup) -> None:
        """错误消息应提示 LLM 使用 tool_search 查询参数格式。"""
        proxy, _, _ = setup
        call = _proxy_call("bash_execute", {})
        result = await proxy.execute(call)
        text = result.content[0].text

        assert "tool_search" in text
