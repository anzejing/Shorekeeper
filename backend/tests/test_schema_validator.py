"""SchemaValidator 测试。"""

from __future__ import annotations

import pytest

from app.tool.schema_validator import SchemaValidator


@pytest.fixture
def validator() -> SchemaValidator:
    return SchemaValidator()


# ─── 辅助 ─────────────────────────────────────────────────


def _simple_schema(**overrides) -> dict:
    """简单 schema：两个必填参数。"""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "名称"},
            "count": {"type": "integer", "description": "数量"},
        },
        "required": ["name", "count"],
    }
    schema.update(overrides)
    return schema


# ─── 必填参数 ─────────────────────────────────────────────


class TestRequired:
    def test_all_required_present(self, validator: SchemaValidator) -> None:
        result = validator.validate("test", {"name": "a", "count": 1}, _simple_schema())
        assert result.valid is True
        assert len(result.errors) == 0

    def test_missing_required(self, validator: SchemaValidator) -> None:
        result = validator.validate("test", {"name": "a"}, _simple_schema())
        assert result.valid is False
        assert any("count" in e for e in result.errors)

    def test_multiple_missing(self, validator: SchemaValidator) -> None:
        result = validator.validate("test", {}, _simple_schema())
        assert result.valid is False
        assert len(result.errors) >= 2

    def test_no_required(self, validator: SchemaValidator) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": [],
        }
        result = validator.validate("test", {}, schema)
        assert result.valid is True


# ─── 类型校验 ─────────────────────────────────────────────


class TestType:
    def test_string_ok(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "string"}}, "required": ["x"]}
        result = validator.validate("test", {"x": "hello"}, schema)
        assert result.valid is True

    def test_string_wrong_type(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "string"}}, "required": ["x"]}
        result = validator.validate("test", {"x": 123}, schema)
        assert result.valid is False
        assert any("类型错误" in e for e in result.errors)

    def test_integer_ok(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "integer"}}, "required": ["x"]}
        result = validator.validate("test", {"x": 42}, schema)
        assert result.valid is True

    def test_integer_rejects_bool(self, validator: SchemaValidator) -> None:
        """Python 中 bool 是 int 子类，但语义上不应通过 integer 校验。"""
        schema = {"properties": {"x": {"type": "integer"}}, "required": ["x"]}
        result = validator.validate("test", {"x": True}, schema)
        assert result.valid is False

    def test_number_accepts_float(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "number"}}, "required": ["x"]}
        result = validator.validate("test", {"x": 3.14}, schema)
        assert result.valid is True

    def test_boolean_ok(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "boolean"}}, "required": ["x"]}
        result = validator.validate("test", {"x": True}, schema)
        assert result.valid is True

    def test_boolean_rejects_string(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "boolean"}}, "required": ["x"]}
        result = validator.validate("test", {"x": "true"}, schema)
        assert result.valid is False

    def test_array_ok(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "array"}}, "required": ["x"]}
        result = validator.validate("test", {"x": [1, 2, 3]}, schema)
        assert result.valid is True

    def test_object_ok(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "object"}}, "required": ["x"]}
        result = validator.validate("test", {"x": {"key": "val"}}, schema)
        assert result.valid is True


# ─── enum 校验 ─────────────────────────────────────────────


class TestEnum:
    def test_enum_ok(self, validator: SchemaValidator) -> None:
        schema = {
            "properties": {"x": {"type": "string", "enum": ["a", "b", "c"]}},
            "required": ["x"],
        }
        result = validator.validate("test", {"x": "b"}, schema)
        assert result.valid is True

    def test_enum_invalid(self, validator: SchemaValidator) -> None:
        schema = {
            "properties": {"x": {"type": "string", "enum": ["a", "b", "c"]}},
            "required": ["x"],
        }
        result = validator.validate("test", {"x": "d"}, schema)
        assert result.valid is False
        assert any("不在允许范围内" in e for e in result.errors)


# ─── 数值约束 ─────────────────────────────────────────────


class TestNumericConstraints:
    def test_minimum_ok(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "integer", "minimum": 0}}, "required": ["x"]}
        result = validator.validate("test", {"x": 5}, schema)
        assert result.valid is True

    def test_minimum_violated(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "integer", "minimum": 0}}, "required": ["x"]}
        result = validator.validate("test", {"x": -1}, schema)
        assert result.valid is False
        assert any("最小值" in e for e in result.errors)

    def test_maximum_ok(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "integer", "maximum": 100}}, "required": ["x"]}
        result = validator.validate("test", {"x": 50}, schema)
        assert result.valid is True

    def test_maximum_violated(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "integer", "maximum": 100}}, "required": ["x"]}
        result = validator.validate("test", {"x": 200}, schema)
        assert result.valid is False
        assert any("最大值" in e for e in result.errors)


# ─── 字符串约束 ────────────────────────────────────────────


class TestStringConstraints:
    def test_min_length_ok(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "string", "minLength": 3}}, "required": ["x"]}
        result = validator.validate("test", {"x": "hello"}, schema)
        assert result.valid is True

    def test_min_length_violated(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "string", "minLength": 3}}, "required": ["x"]}
        result = validator.validate("test", {"x": "ab"}, schema)
        assert result.valid is False


# ─── 数组约束 ─────────────────────────────────────────────


class TestArrayConstraints:
    def test_min_items_ok(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "array", "minItems": 2}}, "required": ["x"]}
        result = validator.validate("test", {"x": [1, 2, 3]}, schema)
        assert result.valid is True

    def test_min_items_violated(self, validator: SchemaValidator) -> None:
        schema = {"properties": {"x": {"type": "array", "minItems": 2}}, "required": ["x"]}
        result = validator.validate("test", {"x": [1]}, schema)
        assert result.valid is False

    def test_items_type_ok(self, validator: SchemaValidator) -> None:
        schema = {
            "properties": {
                "x": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["x"],
        }
        result = validator.validate("test", {"x": ["a", "b"]}, schema)
        assert result.valid is True

    def test_items_type_violated(self, validator: SchemaValidator) -> None:
        schema = {
            "properties": {
                "x": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["x"],
        }
        result = validator.validate("test", {"x": ["a", 123]}, schema)
        assert result.valid is False


# ─── 嵌套对象 ─────────────────────────────────────────────


class TestNestedObject:
    def test_nested_required_ok(self, validator: SchemaValidator) -> None:
        schema = {
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string"},
                        "port": {"type": "integer"},
                    },
                    "required": ["host"],
                }
            },
            "required": ["config"],
        }
        result = validator.validate("test", {"config": {"host": "localhost"}}, schema)
        assert result.valid is True

    def test_nested_required_missing(self, validator: SchemaValidator) -> None:
        schema = {
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {"host": {"type": "string"}},
                    "required": ["host"],
                }
            },
            "required": ["config"],
        }
        result = validator.validate("test", {"config": {}}, schema)
        assert result.valid is False


# ─── 未知参数警告 ──────────────────────────────────────────


class TestUnknownParams:
    def test_unknown_param_warns(self, validator: SchemaValidator) -> None:
        schema = _simple_schema()
        result = validator.validate("test", {"name": "a", "count": 1, "extra": "val"}, schema)
        assert result.valid is True  # 不阻止执行
        assert len(result.warnings) == 1
        assert "extra" in result.warnings[0]


# ─── 空 schema ────────────────────────────────────────────


class TestEmptySchema:
    def test_no_schema_skips(self, validator: SchemaValidator) -> None:
        result = validator.validate("test", {"anything": "goes"}, {})
        assert result.valid is True

    def test_none_schema_skips(self, validator: SchemaValidator) -> None:
        result = validator.validate("test", {"anything": "goes"}, None)
        assert result.valid is True


# ─── 修正建议 ─────────────────────────────────────────────


class TestSuggestion:
    def test_suggestion_on_missing(self, validator: SchemaValidator) -> None:
        result = validator.validate("test", {}, _simple_schema())
        assert result.valid is False
        assert result.suggestion  # 有修正建议

    def test_suggestion_empty_on_success(self, validator: SchemaValidator) -> None:
        result = validator.validate("test", {"name": "a", "count": 1}, _simple_schema())
        assert result.valid is True
        assert result.suggestion == ""
