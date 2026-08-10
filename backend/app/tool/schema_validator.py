"""SchemaValidator — JSON Schema 参数校验器。

校验 LLM 传入的参数是否符合工具定义的 JSON Schema。
返回详细错误信息，引导 LLM 自行修正。

支持的 JSON Schema 特性：
- required 必填字段
- type 类型（string, integer, number, boolean, array, object）
- enum 枚举值
- minimum / maximum（数值范围）
- minLength / maxLength（字符串长度）
- minItems / maxItems（数组长度）
- 嵌套对象（递归，深度上限 3 层）
- items（数组元素类型）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# 嵌套校验深度上限
_MAX_DEPTH = 3


@dataclass
class ValidationResult:
    """校验结果。"""

    valid: bool                            # 是否通过
    errors: list[str] = field(default_factory=list)     # 阻塞错误
    warnings: list[str] = field(default_factory=list)   # 非阻塞警告
    suggestion: str = ""                   # 修正建议


class SchemaValidator:
    """JSON Schema 参数校验器。

    校验规则：
    1. required 字段必须存在
    2. 类型必须匹配
    3. enum 值必须在允许范围内
    4. 数值范围、字符串长度、数组长度等约束
    5. 未知参数产生警告（不阻止执行）
    """

    def validate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        schema: dict[str, Any],
    ) -> ValidationResult:
        """校验参数。

        Args:
            tool_name: 工具名称（用于错误消息）。
            arguments: LLM 传入的参数。
            schema: 工具的 JSON Schema 参数定义。

        Returns:
            ValidationResult 校验结果。
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not schema:
            # 无 schema 定义 → 跳过校验
            return ValidationResult(valid=True)

        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # 1. 检查未知参数
        for arg_name in arguments:
            if arg_name not in properties:
                warnings.append(
                    f"参数 '{arg_name}' 不在工具定义中，将被忽略"
                )

        # 2. 检查必填参数
        for req_name in required:
            if req_name not in arguments:
                param_def = properties.get(req_name, {})
                errors.append(
                    f"缺少必填参数: '{req_name}'"
                    + (f" ({param_def.get('description', '')})" if param_def.get('description') else "")
                )

        # 3. 逐个校验参数类型和约束
        for arg_name, arg_value in arguments.items():
            param_def = properties.get(arg_name)
            if param_def is None:
                continue  # 未知参数已在 warnings 中处理

            param_errors = self._validate_value(
                arg_name, arg_value, param_def, depth=0
            )
            errors.extend(param_errors)

        # 4. 生成修正建议
        suggestion = self._build_suggestion(tool_name, errors, warnings, schema)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            suggestion=suggestion,
        )

    def _validate_value(
        self,
        name: str,
        value: Any,
        schema: dict[str, Any],
        depth: int,
    ) -> list[str]:
        """校验单个值的类型和约束。"""
        errors: list[str] = []

        if depth > _MAX_DEPTH:
            return errors  # 超过深度限制，跳过嵌套校验

        expected_type = schema.get("type")
        if expected_type is None:
            return errors  # 无类型定义，跳过

        # 类型校验
        type_error = self._check_type(name, value, expected_type)
        if type_error:
            errors.append(type_error)
            return errors  # 类型不对，后续校验无意义

        # enum 校验
        enum_values = schema.get("enum")
        if enum_values and value not in enum_values:
            errors.append(
                f"参数 '{name}' 的值 '{value}' 不在允许范围内。"
                f"可选值: {enum_values}"
            )

        # 数值约束
        if expected_type in ("integer", "number"):
            if isinstance(value, (int, float)):
                min_val = schema.get("minimum")
                max_val = schema.get("maximum")
                if min_val is not None and value < min_val:
                    errors.append(f"参数 '{name}' 的值 {value} 小于最小值 {min_val}")
                if max_val is not None and value > max_val:
                    errors.append(f"参数 '{name}' 的值 {value} 大于最大值 {max_val}")

        # 字符串约束
        if expected_type == "string" and isinstance(value, str):
            min_len = schema.get("minLength")
            max_len = schema.get("maxLength")
            if min_len is not None and len(value) < min_len:
                errors.append(f"参数 '{name}' 的长度 {len(value)} 小于最小长度 {min_len}")
            if max_len is not None and len(value) > max_len:
                errors.append(f"参数 '{name}' 的长度 {len(value)} 大于最大长度 {max_len}")

        # 数组约束
        if expected_type == "array" and isinstance(value, list):
            min_items = schema.get("minItems")
            max_items = schema.get("maxItems")
            if min_items is not None and len(value) < min_items:
                errors.append(f"参数 '{name}' 的元素数 {len(value)} 少于最少 {min_items} 个")
            if max_items is not None and len(value) > max_items:
                errors.append(f"参数 '{name}' 的元素数 {len(value)} 多于最多 {max_items} 个")

            # 校验数组元素类型
            items_schema = schema.get("items")
            if items_schema and isinstance(items_schema, dict):
                for i, item in enumerate(value):
                    item_errors = self._validate_value(
                        f"{name}[{i}]", item, items_schema, depth + 1
                    )
                    errors.extend(item_errors)

        # 嵌套对象约束
        if expected_type == "object" and isinstance(value, dict):
            nested_props = schema.get("properties", {})
            nested_required = schema.get("required", [])
            for req in nested_required:
                if req not in value:
                    errors.append(f"参数 '{name}.{req}' 是必填的嵌套字段")
            for prop_name, prop_value in value.items():
                if prop_name in nested_props:
                    prop_errors = self._validate_value(
                        f"{name}.{prop_name}",
                        prop_value,
                        nested_props[prop_name],
                        depth + 1,
                    )
                    errors.extend(prop_errors)

        return errors

    @staticmethod
    def _check_type(name: str, value: Any, expected_type: str) -> str | None:
        """检查值的类型，返回错误消息或 None。"""
        type_checks = {
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "array": lambda v: isinstance(v, list),
            "object": lambda v: isinstance(v, dict),
        }

        check = type_checks.get(expected_type)
        if check is None:
            return None  # 未知类型，跳过

        if not check(value):
            actual_type = type(value).__name__
            return (
                f"参数 '{name}' 类型错误: "
                f"期望 {expected_type}，实际 {actual_type}。"
                f"当前值: {json.dumps(value, ensure_ascii=False)}"
            )

        return None

    @staticmethod
    def _build_suggestion(
        tool_name: str,
        errors: list[str],
        warnings: list[str],
        schema: dict[str, Any],
    ) -> str:
        """根据错误类型生成修正建议。"""
        if not errors and not warnings:
            return ""

        parts: list[str] = []

        # 必填参数缺失
        missing = [e for e in errors if "缺少必填参数" in e]
        if missing:
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            param_table = []
            for req_name in required:
                prop = properties.get(req_name, {})
                param_table.append(
                    f"  - {req_name} ({prop.get('type', 'any')}, 必填): "
                    f"{prop.get('description', '无描述')}"
                )
            parts.append("必填参数:\n" + "\n".join(param_table))

        # 类型错误
        type_errors = [e for e in errors if "类型错误" in e]
        if type_errors:
            parts.append(
                "请确保参数类型与工具定义一致。"
                "如果不确定工具的参数格式，请先调用 tool_search 查询。"
            )

        # 未知参数
        if warnings:
            parts.append("未知参数会被忽略，请检查工具名和参数名是否正确。")

        return "\n".join(parts)
