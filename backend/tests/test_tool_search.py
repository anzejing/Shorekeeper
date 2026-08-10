"""ToolSearchExecutor 测试。"""

from __future__ import annotations

import pytest

from app.runtime.models import ToolCall
from app.tool.index import ToolIndex, ToolIndexEntry
from app.tool.search import ToolSearchExecutor


@pytest.fixture
def index() -> ToolIndex:
    idx = ToolIndex()
    idx.add(ToolIndexEntry(
        name="bash_execute",
        description="执行 shell 命令",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"},
            },
            "required": ["command"],
        },
        category="core",
        source="builtin",
        tags=["shell", "命令", "bash"],
    ))
    idx.add(ToolIndexEntry(
        name="read_file",
        description="读取文件内容",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "offset": {"type": "integer", "default": 0, "description": "起始行"},
                "limit": {"type": "integer", "default": 200, "description": "最大行数"},
            },
            "required": ["path"],
        },
        category="core",
        source="builtin",
        tags=["文件", "读取"],
    ))
    idx.add(ToolIndexEntry(
        name="slack/send_message",
        description="发送 Slack 消息到指定频道",
        parameters={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "频道名"},
                "text": {"type": "string", "description": "消息内容"},
            },
            "required": ["channel", "text"],
        },
        category="mcp",
        source="slack",
        tags=["slack", "消息", "发送"],
    ))
    return idx


@pytest.fixture
def executor(index: ToolIndex) -> ToolSearchExecutor:
    return ToolSearchExecutor(index)


def _make_call(query: str, category: str | None = None) -> ToolCall:
    args = {"query": query}
    if category:
        args["category"] = category
    return ToolCall(tool_call_id="tc-1", tool_name="tool_search", arguments=args)


# ─── 测试 ─────────────────────────────────────────────────


class TestToolSearch:
    @pytest.mark.asyncio
    async def test_search_by_query(self, executor: ToolSearchExecutor) -> None:
        result = await executor.execute(_make_call("执行命令"))
        assert result.is_error is False
        assert "bash_execute" in result.content[0].text

    @pytest.mark.asyncio
    async def test_search_returns_full_definition(self, executor: ToolSearchExecutor) -> None:
        """搜索结果应包含完整参数定义。"""
        result = await executor.execute(_make_call("slack"))
        text = result.content[0].text
        assert "slack/send_message" in text
        assert "channel" in text
        assert "text" in text
        assert "必填" in text

    @pytest.mark.asyncio
    async def test_search_with_category(self, executor: ToolSearchExecutor) -> None:
        result = await executor.execute(_make_call("消息", category="mcp"))
        text = result.content[0].text
        assert "slack/send_message" in text
        assert "bash_execute" not in text

    @pytest.mark.asyncio
    async def test_search_empty_query(self, executor: ToolSearchExecutor) -> None:
        result = await executor.execute(_make_call(""))
        assert result.is_error is True
        assert "搜索关键词" in result.content[0].text

    @pytest.mark.asyncio
    async def test_search_no_results(self, executor: ToolSearchExecutor) -> None:
        result = await executor.execute(_make_call("量子计算 超导"))
        assert result.is_error is False
        assert "未找到" in result.content[0].text

    @pytest.mark.asyncio
    async def test_search_multiple_results(self, executor: ToolSearchExecutor) -> None:
        """搜索通用词应返回多个结果。"""
        result = await executor.execute(_make_call("工具"))
        text = result.content[0].text
        assert "找到" in text

    @pytest.mark.asyncio
    async def test_search_usage_hint(self, executor: ToolSearchExecutor) -> None:
        """搜索结果末尾应包含使用方法提示。"""
        result = await executor.execute(_make_call("slack"))
        text = result.content[0].text
        assert "tool_executor" in text

    @pytest.mark.asyncio
    async def test_search_required_label(self, executor: ToolSearchExecutor) -> None:
        """必填参数应标注为 '必填'。"""
        result = await executor.execute(_make_call("slack"))
        text = result.content[0].text
        assert "必填" in text

    @pytest.mark.asyncio
    async def test_search_optional_label(self, executor: ToolSearchExecutor) -> None:
        """可选参数应标注为 '可选'。"""
        result = await executor.execute(_make_call("read_file"))
        text = result.content[0].text
        assert "可选" in text
