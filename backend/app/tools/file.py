"""read_file / write_file Tool — 文件读写。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.runtime.models import TextPart, ToolCall, ToolResult

log = logging.getLogger(__name__)


class ReadFileExecutor:
    """read_file 工具执行器。"""

    def __init__(self, max_lines: int = 1000) -> None:
        self._max_lines = max_lines

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        path_str = tool_call.arguments.get("path", "")
        offset = tool_call.arguments.get("offset", 0)
        limit = tool_call.arguments.get("limit", 200)

        if not path_str:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="read_file",
                content=[TextPart(text="错误：未提供 path 参数")],
                is_error=True,
            )

        path = Path(path_str).expanduser()

        try:
            if not path.exists():
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    tool_name="read_file",
                    content=[TextPart(text=f"文件不存在: {path}")],
                    is_error=True,
                )

            if not path.is_file():
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    tool_name="read_file",
                    content=[TextPart(text=f"不是文件: {path}")],
                    is_error=True,
                )

            # 检查文件大小（限制 10MB）
            size = path.stat().st_size
            if size > 10 * 1024 * 1024:
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    tool_name="read_file",
                    content=[TextPart(text=f"文件过大 ({size / 1024 / 1024:.1f}MB)，超过 10MB 限制")],
                    is_error=True,
                )

            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)

            # 应用 offset 和 limit
            selected = lines[offset:offset + limit]

            if not selected:
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    tool_name="read_file",
                    content=[TextPart(text=f"文件为空或 offset 超出范围（总行数: {total}）")],
                )

            # 添加行号
            numbered = []
            for i, line in enumerate(selected, start=offset + 1):
                numbered.append(f"{i:4d} | {line}")

            output = "\n".join(numbered)

            # 添加文件信息头
            header = f"文件: {path} ({total} 行)"
            if offset > 0 or offset + limit < total:
                header += f" [显示 {offset+1}-{min(offset+limit, total)}]"

            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="read_file",
                content=[TextPart(text=f"{header}\n{output}")],
            )

        except PermissionError:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="read_file",
                content=[TextPart(text=f"权限不足: {path}")],
                is_error=True,
            )
        except Exception as e:
            log.exception("read_file 失败: %s", path)
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="read_file",
                content=[TextPart(text=f"读取失败: {e}")],
                is_error=True,
            )


class WriteFileExecutor:
    """write_file 工具执行器。"""

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        path_str = tool_call.arguments.get("path", "")
        content = tool_call.arguments.get("content", "")

        if not path_str:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="write_file",
                content=[TextPart(text="错误：未提供 path 参数")],
                is_error=True,
            )

        path = Path(path_str).expanduser()

        try:
            # 创建父目录
            path.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            path.write_text(content, encoding="utf-8")

            lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="write_file",
                content=[TextPart(text=f"已写入 {path} ({lines} 行, {len(content)} 字节)")],
            )

        except PermissionError:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="write_file",
                content=[TextPart(text=f"权限不足: {path}")],
                is_error=True,
            )
        except Exception as e:
            log.exception("write_file 失败: %s", path)
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="write_file",
                content=[TextPart(text=f"写入失败: {e}")],
                is_error=True,
            )
