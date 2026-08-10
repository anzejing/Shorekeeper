"""ToolIndex 测试。"""

from __future__ import annotations

import pytest

from app.tool.index import ToolIndex, ToolIndexEntry


# ─── 辅助 ─────────────────────────────────────────────────


def _make_entry(
    name: str = "test_tool",
    description: str = "测试工具",
    category: str = "core",
    tags: list[str] | None = None,
    properties: dict | None = None,
) -> ToolIndexEntry:
    return ToolIndexEntry(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties or {},
        },
        category=category,
        source="test",
        tags=tags or [],
    )


# ─── 基础操作 ─────────────────────────────────────────────


class TestAddRemove:
    def test_add_and_get(self) -> None:
        index = ToolIndex()
        entry = _make_entry("bash_execute", "执行 shell 命令")
        index.add(entry)

        assert index.count() == 1
        assert index.get("bash_execute") is entry

    def test_add_overwrite(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a", "描述1"))
        index.add(_make_entry("tool_a", "描述2"))

        assert index.count() == 1
        assert index.get("tool_a").description == "描述2"

    def test_remove(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a"))
        result = index.remove("tool_a")

        assert result is True
        assert index.count() == 0
        assert index.get("tool_a") is None

    def test_remove_not_found(self) -> None:
        index = ToolIndex()
        assert index.remove("nonexistent") is False

    def test_list_all(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a"))
        index.add(_make_entry("tool_b"))

        all_entries = index.list_all()
        assert len(all_entries) == 2
        names = {e.name for e in all_entries}
        assert names == {"tool_a", "tool_b"}


# ─── 搜索 ─────────────────────────────────────────────────


class TestSearch:
    def test_search_by_name(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("bash_execute", "执行 shell 命令"))
        index.add(_make_entry("read_file", "读取文件"))

        results = index.search("bash")
        assert len(results) == 1
        assert results[0].name == "bash_execute"

    def test_search_by_description(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a", "发送 Slack 消息"))
        index.add(_make_entry("tool_b", "读取文件内容"))

        results = index.search("发送消息")
        assert len(results) >= 1
        assert results[0].name == "tool_a"

    def test_search_by_tags(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a", "操作A", tags=["slack", "消息"]))
        index.add(_make_entry("tool_b", "操作B", tags=["file", "读取"]))

        results = index.search("slack")
        assert len(results) >= 1
        assert results[0].name == "tool_a"

    def test_search_by_property_name(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a", "发消息", properties={
            "channel": {"type": "string", "description": "Slack 频道"},
        }))
        index.add(_make_entry("tool_b", "读文件", properties={
            "path": {"type": "string", "description": "文件路径"},
        }))

        results = index.search("channel")
        assert len(results) >= 1
        assert results[0].name == "tool_a"

    def test_search_with_category_filter(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a", "MCP 工具", category="mcp"))
        index.add(_make_entry("tool_b", "核心工具", category="core"))

        results = index.search("工具", category="mcp")
        assert len(results) == 1
        assert results[0].name == "tool_a"

    def test_search_empty_query_returns_all(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a"))
        index.add(_make_entry("tool_b"))

        results = index.search("")
        assert len(results) == 2

    def test_search_no_results(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("bash_execute", "执行命令"))

        results = index.search("slack 消息发送")
        assert len(results) == 0

    def test_search_limit(self) -> None:
        index = ToolIndex()
        for i in range(10):
            index.add(_make_entry(f"tool_{i}", f"工具 {i} 操作"))

        results = index.search("工具", limit=3)
        assert len(results) == 3

    def test_search_relevance_order(self) -> None:
        """名称完全匹配的应该排在前面。"""
        index = ToolIndex()
        index.add(_make_entry("send_message", "发送消息"))
        index.add(_make_entry("read_file", "读取消息日志文件"))

        results = index.search("send_message")
        assert len(results) >= 1
        assert results[0].name == "send_message"

    def test_search_after_remove(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a", "发送消息"))
        index.remove("tool_a")

        results = index.search("消息")
        assert len(results) == 0

    def test_search_after_overwrite(self) -> None:
        index = ToolIndex()
        index.add(_make_entry("tool_a", "旧描述"))
        index.add(_make_entry("tool_a", "新描述 不同内容"))

        results = index.search("新描述")
        assert len(results) == 1
        assert results[0].description == "新描述 不同内容"
