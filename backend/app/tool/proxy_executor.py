"""ProxyToolExecutor — 通用代理执行器。

路由到任意已注册工具，附带参数校验。
供 LLM 通过 tool_executor 调用动态工具（MCP、插件等）。

流程：
1. 解析 tool_name + arguments
2. 参数校验（SchemaValidator）
3. 路由到 ToolRegistry 执行
4. 返回结果或详细错误信息

安全：
- 禁止自路由（tool_executor 不能调用自身）
- 禁止调用 tool_search（应直接调用）
- 动态工具走完整权限审批流程（由 PermissionInterceptor 保证）
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.runtime.models import TextPart, ToolCall, ToolResult
from app.tool.registry import ToolRegistry
from app.tool.schema_validator import SchemaValidator, ValidationResult

log = logging.getLogger(__name__)

# 禁止通过 tool_executor 调用的工具
_BLOCKED_TOOLS = frozenset({"tool_executor", "tool_search"})


class ProxyToolExecutor:
    """代理执行器——路由到任意已注册工具。

    注册为 tool_executor 工具的执行器。
    LLM 调用 tool_executor(tool_name="...", arguments={...})，
    本执行器校验参数后路由到实际工具。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        validator: SchemaValidator,
    ) -> None:
        self._registry = registry
        self._validator = validator

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """执行代理调用。"""
        args = tool_call.arguments
        target_name = args.get("tool_name", "")
        target_args = args.get("arguments", {})

        # 1. 参数存在性检查
        if not target_name:
            return self._format_error(
                tool_call,
                "缺少 tool_name 参数。请指定要执行的工具名称。",
                hint="调用 tool_search(query='...') 可以查找可用工具。",
            )

        if not isinstance(target_args, dict):
            return self._format_error(
                tool_call,
                f"arguments 必须是对象类型，实际是 {type(target_args).__name__}。",
                hint="arguments 应为 JSON 对象，例如: {\"key\": \"value\"}",
            )

        # 2. 禁止自路由和禁止调用的工具
        if target_name in _BLOCKED_TOOLS:
            return self._format_error(
                tool_call,
                f"不允许通过 tool_executor 调用 '{target_name}'。",
                hint=(
                    "tool_search 请直接调用，不要通过 tool_executor。\n"
                    "tool_executor 不允许调用自身。"
                ),
            )

        # 3. 工具存在性检查
        target_def = self._registry.get_tool(target_name)
        if target_def is None:
            available = [
                td.name for td in self._registry.get_all_tools()
                if td.name not in _BLOCKED_TOOLS
            ]
            return self._format_error(
                tool_call,
                f"工具 '{target_name}' 不存在。",
                hint=(
                    f"请先调用 tool_search(query='你需要的功能') 查找正确的工具名。\n"
                    f"可用的固定工具: {', '.join(available[:10])}"
                ),
            )

        # 4. 参数校验
        validation = self._validator.validate(
            target_name, target_args, target_def.parameters
        )
        if not validation.valid:
            return self._format_validation_error(
                tool_call, target_name, target_args, target_def, validation
            )

        # 5. 构造实际 ToolCall 并执行
        actual_call = ToolCall(
            tool_call_id=tool_call.tool_call_id,
            tool_name=target_name,
            arguments=target_args,
        )

        log.info(
            "ProxyToolExecutor: 路由 %s → %s",
            tool_call.tool_name, target_name,
        )

        result = await self._registry.execute(
            actual_call, cancellation=cancellation, context=context
        )

        # 6. 附加警告到结果
        if validation.warnings and not result.is_error:
            warning_text = "⚠️ 注意:\n" + "\n".join(validation.warnings) + "\n\n"
            result.content.insert(0, TextPart(text=warning_text))

        return result

    # ─── 错误消息格式化 ──────────────────────────────────

    @staticmethod
    def _format_error(
        tool_call: ToolCall,
        message: str,
        hint: str = "",
    ) -> ToolResult:
        """格式化通用错误。"""
        parts = [f"❌ tool_executor 执行失败\n\n错误: {message}"]
        if hint:
            parts.append(f"\n💡 提示: {hint}")

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name="tool_executor",
            content=[TextPart(text="\n".join(parts))],
            is_error=True,
        )

    @staticmethod
    def _format_validation_error(
        tool_call: ToolCall,
        target_name: str,
        target_args: dict[str, Any],
        target_def: Any,
        validation: ValidationResult,
    ) -> ToolResult:
        """格式化参数校验错误——提供完整信息引导 LLM 修正。"""
        parts = [
            f"❌ tool_executor 参数校验失败",
            f"",
            f"目标工具: {target_name}",
            f"",
            f"错误原因:",
        ]

        for error in validation.errors:
            parts.append(f"  • {error}")

        # 格式化参数定义
        properties = target_def.parameters.get("properties", {})
        required = target_def.parameters.get("required", [])

        if properties:
            parts.append("")
            parts.append("参数定义:")
            for prop_name, prop_def in properties.items():
                if not isinstance(prop_def, dict):
                    continue
                prop_type = prop_def.get("type", "any")
                is_required = prop_name in required
                req_label = "必填" if is_required else "可选"
                default = prop_def.get("default")
                default_label = f", 默认 {default}" if default is not None else ""
                desc = prop_def.get("description", "")
                parts.append(
                    f"  - {prop_name} ({prop_type}, {req_label}{default_label}): {desc}"
                )

        # 显示 LLM 传入的参数
        parts.append("")
        parts.append(f"你提供的参数: {json.dumps(target_args, ensure_ascii=False)}")

        # 修正建议
        if validation.suggestion:
            parts.append("")
            parts.append(f"💡 修正建议:")
            parts.append(validation.suggestion)

        parts.append("")
        parts.append("提示: 如果不确定工具的参数格式，请先调用 tool_search(query='工具名') 查询。")

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name="tool_executor",
            content=[TextPart(text="\n".join(parts))],
            is_error=True,
        )
