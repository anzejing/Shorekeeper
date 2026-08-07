"""PluginLoader 测试（插件发现 + 命名空间）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.plugin.loader import PluginLoader
from app.runtime.store import init_db
from app.skill.loader import SkillLoader
from app.skill.store import SQLiteSkillStore, init_skill_db


# ─── 辅助 ─────────────────────────────────────────────────


async def _make_loader(
    plugins_dir: Path,
) -> tuple[PluginLoader, SkillLoader]:
    db = await init_db()
    await init_skill_db(db)
    store = SQLiteSkillStore(db)
    skill_loader = SkillLoader(plugins_dir.parent / "skills", store)
    return PluginLoader(plugins_dir, skill_loader), skill_loader


def _write_plugin(
    plugins_dir: Path,
    plugin_name: str,
    skills: dict[str, str] | None = None,
    manifest: dict | None = None,
) -> None:
    """写入一个测试插件目录。skills: {skill_name: SKILL.md 内容}。"""
    plugin_dir = plugins_dir / plugin_name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    m = manifest or {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": plugin_name,
        "version": "1.0.0",
        "description": "测试插件",
    }
    (plugin_dir / "plugin.json").write_text(
        __import__("json").dumps(m), encoding="utf-8"
    )

    for skill_name, content in (skills or {}).items():
        skill_dir = plugin_dir / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


# ─── 插件发现 ─────────────────────────────────────────────


class TestPluginScan:
    @pytest.mark.asyncio
    async def test_discover_single_skill(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _write_plugin(
            plugins_dir,
            "hello-plugin",
            skills={
                "greet": """---
name: greet
description: 问候用户
---

Greet the user.
""",
            },
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert len(infos) == 1
        info = infos[0]
        # 命名空间：逻辑名 = plugin-name/skill-name
        assert info.name == "hello-plugin/greet"
        assert info.plugin_name == "hello-plugin"
        assert info.description == "问候用户"
        assert "Greet the user" in info.system_prompt

    @pytest.mark.asyncio
    async def test_discover_multiple_skills(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _write_plugin(
            plugins_dir,
            "multi",
            skills={
                "skill-a": "---\nname: skill-a\ndescription: A\n---\n\nA",
                "skill-b": "---\nname: skill-b\ndescription: B\n---\n\nB",
            },
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert {i.name for i in infos} == {"multi/skill-a", "multi/skill-b"}
        assert all(i.plugin_name == "multi" for i in infos)

    @pytest.mark.asyncio
    async def test_skip_dir_without_manifest(self, tmp_path: Path) -> None:
        """§6.2 缺失 plugin.json 不算错误，跳过。"""
        plugins_dir = tmp_path / "plugins"
        (plugins_dir / "no-manifest" / "skills").mkdir(parents=True)
        (plugins_dir / "no-manifest" / "skills" / "x" / "SKILL.md").parent.mkdir()
        (plugins_dir / "no-manifest" / "skills" / "x" / "SKILL.md").write_text(
            "---\nname: x\ndescription: X\n---\n\nX", encoding="utf-8"
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert infos == []

    @pytest.mark.asyncio
    async def test_skip_invalid_manifest(self, tmp_path: Path) -> None:
        """§11.3 单个插件失败不阻塞其他插件。"""
        plugins_dir = tmp_path / "plugins"
        # 无效插件：缺 $schema
        _write_plugin(plugins_dir, "bad", manifest={"name": "bad"})
        # 有效插件
        _write_plugin(
            plugins_dir,
            "good",
            skills={"ok": "---\nname: ok\ndescription: OK\n---\n\nOK"},
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert len(infos) == 1
        assert infos[0].name == "good/ok"

    @pytest.mark.asyncio
    async def test_skip_invalid_skill(self, tmp_path: Path) -> None:
        """§7.1 无效 SKILL.md 跳过该 skill，继续其他。"""
        plugins_dir = tmp_path / "plugins"
        _write_plugin(
            plugins_dir,
            "p",
            skills={
                "valid": "---\nname: valid\ndescription: OK\n---\n\nOK",
                "invalid": "# 没有 frontmatter 的无效 skill",
            },
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert [i.name for i in infos] == ["p/valid"]

    @pytest.mark.asyncio
    async def test_skip_non_recursive(self, tmp_path: Path) -> None:
        """§7.1 不递归搜索更深层目录。"""
        plugins_dir = tmp_path / "plugins"
        _write_plugin(
            plugins_dir,
            "p",
            skills={"top": "---\nname: top\ndescription: T\n---\n\nT"},
        )
        # 深层 SKILL.md 不应被发现
        deep = plugins_dir / "p" / "skills" / "top" / "nested"
        deep.mkdir(parents=True)
        (deep / "SKILL.md").write_text(
            "---\nname: nested\ndescription: N\n---\n\nN", encoding="utf-8"
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert [i.name for i in infos] == ["p/top"]

    @pytest.mark.asyncio
    async def test_skip_missing_skills_dir(self, tmp_path: Path) -> None:
        """§6.2 无 skills/ 目录不算错误。"""
        plugins_dir = tmp_path / "plugins"
        _write_plugin(plugins_dir, "empty")

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert infos == []

    @pytest.mark.asyncio
    async def test_multiple_plugins_coexist(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _write_plugin(
            plugins_dir,
            "p1",
            skills={"a": "---\nname: a\ndescription: A\n---\n\nA"},
        )
        _write_plugin(
            plugins_dir,
            "p2",
            skills={"b": "---\nname: b\ndescription: B\n---\n\nB"},
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert {i.name for i in infos} == {"p1/a", "p2/b"}


# ─── frontmatter 兼容 ─────────────────────────────────────


class TestFrontmatterCompat:
    @pytest.mark.asyncio
    async def test_metadata_version(self, tmp_path: Path) -> None:
        """Agent Plugins 规范：metadata.version → version。"""
        plugins_dir = tmp_path / "plugins"
        _write_plugin(
            plugins_dir,
            "p",
            skills={
                "s": """---
name: s
description: 带 metadata.version 的 skill
metadata:
  version: "2.1.0"
---

Body
""",
            },
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert infos[0].version == "2.1.0"

    @pytest.mark.asyncio
    async def test_top_level_version_priority(self, tmp_path: Path) -> None:
        """顶层 version 优先于 metadata.version。"""
        plugins_dir = tmp_path / "plugins"
        _write_plugin(
            plugins_dir,
            "p",
            skills={
                "s": """---
name: s
description: 两者都有
version: 1.5.0
metadata:
  version: "9.9.9"
---

Body
""",
            },
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert infos[0].version == "1.5.0"

    @pytest.mark.asyncio
    async def test_version_default(self, tmp_path: Path) -> None:
        """都缺省时用默认值。"""
        plugins_dir = tmp_path / "plugins"
        _write_plugin(
            plugins_dir,
            "p",
            skills={
                "s": """---
name: s
description: 无版本
---

Body
""",
            },
        )

        loader, _ = await _make_loader(plugins_dir)
        infos = await loader.scan()

        assert infos[0].version == "0.0.0"
