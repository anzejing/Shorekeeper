"""bash_execute Tool — 执行 shell 命令。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.runtime.models import TextPart, ToolCall, ToolResult

log = logging.getLogger(__name__)


class BashExecutor:
    """bash_execute 工具执行器。"""

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        command = tool_call.arguments.get("command", "")
        if not command:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="bash_execute",
                content=[TextPart(text="错误：未提供 command 参数")],
                is_error=True,
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    tool_name="bash_execute",
                    content=[TextPart(text=f"命令超时（{self._timeout}s）: {command}")],
                    is_error=True,
                )

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            parts: list[str] = []
            if stdout_text:
                parts.append(stdout_text)
            if stderr_text:
                parts.append(f"[stderr]\n{stderr_text}")
            if proc.returncode != 0:
                parts.append(f"[exit code: {proc.returncode}]")

            output = "\n".join(parts) if parts else "(无输出)"

            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="bash_execute",
                content=[TextPart(text=output)],
                is_error=proc.returncode != 0,
            )

        except Exception as e:
            log.exception("bash_execute 失败: %s", command)
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                tool_name="bash_execute",
                content=[TextPart(text=f"执行失败: {e}")],
                is_error=True,
            )
