"""plugin.json 清单校验测试（Agent Plugins v1.0.0）。"""

from __future__ import annotations

import pytest

from app.plugin.manifest import ManifestError, validate_manifest


# ─── 辅助 ─────────────────────────────────────────────────


def _valid_manifest(**overrides: object) -> dict:
    data = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "my-plugin",
    }
    data.update(overrides)
    return data


# ─── 合法清单 ─────────────────────────────────────────────


class TestValidManifest:
    def test_minimal(self) -> None:
        manifest = validate_manifest(_valid_manifest())
        assert manifest.name == "my-plugin"

    def test_full(self) -> None:
        data = _valid_manifest(
            version="1.2.0",
            description="测试插件",
            author={"name": "Tester", "email": "t@example.com"},
            license="MIT",
            keywords=["agent", "test"],
            extensions={"com.example.client": {"enabled": True}},
        )
        manifest = validate_manifest(data)
        assert manifest.version == "1.2.0"
        assert manifest.author_name == "Tester"
        assert manifest.keywords == ["agent", "test"]
        assert manifest.extensions == {"com.example.client": {"enabled": True}}

    def test_valid_names(self) -> None:
        for name in ["my-plugin", "acme.tools", "lint3r", "a"]:
            validate_manifest(_valid_manifest(name=name))

    def test_unknown_field_ignored(self) -> None:
        """未知顶层字段：报告并忽略，不致命。"""
        data = _valid_manifest(hooks="ignored", mcpServers={"x": {}})
        manifest = validate_manifest(data)
        assert manifest.name == "my-plugin"


# ─── 致命违规 ─────────────────────────────────────────────


class TestFatalErrors:
    def test_not_object(self) -> None:
        with pytest.raises(ManifestError):
            validate_manifest(["not", "object"])  # type: ignore[arg-type]

    def test_missing_schema(self) -> None:
        with pytest.raises(ManifestError, match="\\$schema"):
            validate_manifest({"name": "my-plugin"})

    def test_unsupported_schema(self) -> None:
        with pytest.raises(ManifestError, match="\\$schema"):
            validate_manifest(
                {
                    "$schema": "https://agent-plugins.org/schemas/0.1.0/plugin.schema.json",
                    "name": "my-plugin",
                }
            )

    def test_missing_name(self) -> None:
        with pytest.raises(ManifestError, match="name"):
            validate_manifest(
                {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"}
            )

    @pytest.mark.parametrize(
        "name",
        [
            "My-Plugin",     # 大写
            "-start",        # 开头连字符
            "end-",          # 结尾连字符
            "has--double",   # 连续连字符
            "too..many",     # 连续句点
            "",              # 空
            "x" * 65,        # 超长
        ],
    )
    def test_invalid_names(self, name: str) -> None:
        with pytest.raises(ManifestError, match="插件名"):
            validate_manifest(_valid_manifest(name=name))

    def test_wrong_type_version(self) -> None:
        with pytest.raises(ManifestError, match="version"):
            validate_manifest(_valid_manifest(version=1.0))  # type: ignore[arg-type]

    def test_wrong_type_author(self) -> None:
        with pytest.raises(ManifestError, match="author"):
            validate_manifest(_valid_manifest(author="not-object"))  # type: ignore[arg-type]

    def test_author_unknown_field(self) -> None:
        with pytest.raises(ManifestError, match="author"):
            validate_manifest(
                _valid_manifest(author={"name": "T", "avatar": "x"})  # type: ignore[dict-item]
            )

    def test_keywords_not_list(self) -> None:
        with pytest.raises(ManifestError, match="keywords"):
            validate_manifest(_valid_manifest(keywords="agent"))  # type: ignore[arg-type]

    def test_non_object_extensions_ignored(self) -> None:
        """§8.1 非对象 extensions 报告并忽略。"""
        manifest = validate_manifest(
            _valid_manifest(extensions="not-object")  # type: ignore[arg-type]
        )
        assert manifest.extensions == {}
