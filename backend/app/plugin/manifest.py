"""Agent Plugins v1.0.0 插件清单（plugin.json）校验。

遵循规范 §5（Manifest）与 §4.1（路径安全）：
- 闭包 schema：只允许 $schema/name/version/description/author/homepage/
  repository/license/keywords/extensions
- 未知顶层字段：报告并忽略（非致命）
- 除未知字段与非对象 extensions 外的 schema 违规：致命（拒绝插件）
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ─── 常量 ─────────────────────────────────────────────────

# v1.0.0 插件清单 schema 的规范标识符
SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

# 闭包 schema 允许的顶层字段
ALLOWED_FIELDS = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
}

# 必填字段
REQUIRED_FIELDS = {"$schema", "name"}

# 插件名约束：1-64 字符，小写字母数字、-、.，首尾字母数字，禁止 -- 和 ..
NAME_PATTERN = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


class ManifestError(Exception):
    """plugin.json 校验失败。"""


@dataclass
class PluginManifest:
    """校验通过的插件清单（只读）。"""

    name: str
    version: str = ""
    description: str = ""
    author_name: str = ""
    license: str = ""
    keywords: list[str] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)


def validate_manifest(data: Any) -> PluginManifest:
    """校验插件清单数据，返回 PluginManifest。

    Args:
        data: plugin.json 解析出的 JSON 数据。

    Returns:
        校验通过的 PluginManifest。

    Raises:
        ManifestError: 致命违规（缺少必填字段 / 字段类型错误 / name 约束违规）。
    """
    if not isinstance(data, dict):
        raise ManifestError("plugin.json 必须是 JSON 对象")

    # $schema：必须是规范的标识符（不支持则拒绝）
    schema = data.get("$schema")
    if not isinstance(schema, str) or schema != SCHEMA_ID:
        raise ManifestError(
            f"不支持的 $schema: {schema!r}（需要 {SCHEMA_ID}）"
        )

    # 必填字段
    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ManifestError(f"缺少必填字段: {sorted(missing)}")

    # name 约束
    name = data["name"]
    if (
        not isinstance(name, str)
        or not (1 <= len(name) <= 64)
        or not NAME_PATTERN.match(name)
    ):
        raise ManifestError(
            f"插件名不合法: {name!r}（小写字母数字、-、.，1-64 字符，首尾字母数字，禁止 -- 和 ..）"
        )

    # 未知顶层字段：报告并忽略（非致命）
    unknown = set(data.keys()) - ALLOWED_FIELDS
    if unknown:
        log.warning("插件清单含未知字段，已忽略: %s", sorted(unknown))

    # 字段类型校验（违规则致命）
    _validate_field_types(data)

    # extensions 必须是对象（非对象则报告并忽略）
    extensions: dict[str, Any] = {}
    if "extensions" in data:
        if isinstance(data["extensions"], dict):
            extensions = data["extensions"]
        else:
            log.warning("extensions 字段不是对象，已忽略")

    # author 对象
    author_name = ""
    author = data.get("author")
    if isinstance(author, dict):
        author_name = author.get("name", "")

    return PluginManifest(
        name=name,
        version=data.get("version", ""),
        description=data.get("description", ""),
        author_name=author_name,
        license=data.get("license", ""),
        keywords=data.get("keywords", []),
        extensions=extensions,
    )


def _validate_field_types(data: dict[str, Any]) -> None:
    """校验可选字段类型（类型错误为致命违规）。"""
    if "version" in data and not isinstance(data["version"], str):
        raise ManifestError("version 必须是字符串")
    if "description" in data and not isinstance(data["description"], str):
        raise ManifestError("description 必须是字符串")
    if "homepage" in data and not isinstance(data["homepage"], str):
        raise ManifestError("homepage 必须是字符串")
    if "repository" in data and not isinstance(data["repository"], str):
        raise ManifestError("repository 必须是字符串")
    if "license" in data and not isinstance(data["license"], str):
        raise ManifestError("license 必须是字符串")

    if "author" in data:
        author = data["author"]
        if not isinstance(author, dict):
            raise ManifestError("author 必须是对象")
        allowed = {"name", "email", "url"}
        extra = set(author.keys()) - allowed
        if extra:
            raise ManifestError(f"author 含未知字段: {sorted(extra)}")
        for key, value in author.items():
            if not isinstance(value, str):
                raise ManifestError(f"author.{key} 必须是字符串")

    if "keywords" in data:
        keywords = data["keywords"]
        if not isinstance(keywords, list) or not all(
            isinstance(k, str) for k in keywords
        ):
            raise ManifestError("keywords 必须是字符串数组")


def load_manifest(manifest_path: Path) -> PluginManifest:
    """从文件加载并校验 plugin.json。

    Args:
        manifest_path: plugin.json 路径。

    Returns:
        校验通过的 PluginManifest。

    Raises:
        ManifestError: 文件不存在 / JSON 解析失败 / 校验失败。
    """
    try:
        text = manifest_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except FileNotFoundError:
        raise ManifestError(f"plugin.json 不存在: {manifest_path}")
    except json.JSONDecodeError as e:
        raise ManifestError(f"plugin.json JSON 解析失败: {e}")

    return validate_manifest(data)
