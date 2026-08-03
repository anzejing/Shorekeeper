"""ToolRegistry 测试。"""

from __future__ import annotations

import pytest

from app.runtime.models import TextPart, ToolCall, ToolDef, ToolResult, SideEffectLevel
from app.tool.registry import ToolRegistry


# ─── 辅助 ─────────────────────────────────────────────────


def _make_tool_def(name: str = "test_tool") -> ToolDef:
    return ToolDef(
        name=name,
        description="测试工具",
        parameters={"type": "object", "properties": {}},
        side_effect_level=SideEffectLevel.READ_ONLY,
    )


class MockExecutor:
    def __init__(self, result: str = "ok") -> None:
        self._result = result
        self.calls: list[ToolCall] = []

    async def execute(self, tool_call: ToolCall, *, cancellation=None, context=None) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text=self._result)],
        )


class FailingExecutor:
    async def execute(self, tool_call: ToolCall, *, cancellation=None, context=None) -> ToolResult:
        raise RuntimeError("执行失败")


# ─── 测试 ─────────────────────────────────────────────────


class TestRegister:
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        td = _make_tool_def("my_tool")
        executor = MockExecutor()

        registry.register(td, executor)

        assert registry.has_tool("my_tool")
        assert registry.get_tool("my_tool") is td
        assert len(registry.get_all_tools()) == 1

    def test_register_overwrite(self) -> None:
        registry = ToolRegistry()
        td1 = _make_tool_def("my_tool")
        td2 = _make_tool_def("my_tool")
        executor = MockExecutor()

        registry.register(td1, executor)
        registry.register(td2, executor)  # 覆盖

        assert registry.get_tool("my_tool") is td2
        assert len(registry.get_all_tools()) == 1

    def test_register_many(self) -> None:
        registry = ToolRegistry()
        tools = [_make_tool_def(f"tool_{i}") for i in range(3)]
        executor = MockExecutor()

        registry.register_many(tools, executor)

        assert len(registry.get_all_tools()) == 3
        for i in range(3):
            assert registry.has_tool(f"tool_{i}")


class TestUnregister:
    def test_unregister(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_tool_def("my_tool"), MockExecutor())

        assert registry.unregister("my_tool") is True
        assert not registry.has_tool("my_tool")
        assert len(registry.get_all_tools()) == 0

    def test_unregister_not_found(self) -> None:
        registry = ToolRegistry()
        assert registry.unregister("nonexistent") is False


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        registry = ToolRegistry()
        executor = MockExecutor("result_ok")
        registry.register(_make_tool_def("my_tool"), executor)

        tool_call = ToolCall(tool_call_id="tc-1", tool_name="my_tool", arguments={})
        result = await registry.execute(tool_call)

        assert result.is_error is False
        assert result.content[0].text == "result_ok"
        assert len(executor.calls) == 1

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self) -> None:
        registry = ToolRegistry()

        tool_call = ToolCall(tool_call_id="tc-1", tool_name="unknown", arguments={})
        result = await registry.execute(tool_call)

        assert result.is_error is True
        assert "未知工具" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_failure(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_tool_def("my_tool"), FailingExecutor())

        tool_call = ToolCall(tool_call_id="tc-1", tool_name="my_tool", arguments={})
        result = await registry.execute(tool_call)

        assert result.is_error is True
        assert "执行失败" in result.content[0].text
