"""SkillLoader 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.runtime.store import init_db
from app.skill.loader import SkillLoader
from app.skill.store import SQLiteSkillStore, init_skill_db


# ─── 辅助 ─────────────────────────────────────────────────


async def _make_loader(skills_dir: Path) -> tuple[SkillLoader, SQLiteSkillStore]:
    db = await init_db()
    await init_skill_db(db)
    store = SQLiteSkillStore(db)
    return SkillLoader(skills_dir, store), store


# ─── 解析测试 ─────────────────────────────────────────────


class TestParseSkillMd:
    @pytest.mark.asyncio
    async def test_parse_valid(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            """---
name: test
description: 测试 Skill
category: utility
version: 1.0.0
author: test
---

# Test Skill

这是测试提示词。
""",
            encoding="utf-8",
        )

        loader, _ = await _make_loader(tmp_path)
        info = loader._parse_skill_md(skill_md)

        assert info is not None
        assert info.name == "test"
        assert info.description == "测试 Skill"
        assert info.category == "utility"
        assert info.version == "1.0.0"
        assert "测试提示词" in info.system_prompt

    @pytest.mark.asyncio
    async def test_parse_missing_name(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            """---
description: 没有 name
---

body
""",
            encoding="utf-8",
        )

        loader, _ = await _make_loader(tmp_path)
        info = loader._parse_skill_md(skill_md)
        assert info is None

    @pytest.mark.asyncio
    async def test_parse_no_frontmatter(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("没有 frontmatter 的文件", encoding="utf-8")

        loader, _ = await _make_loader(tmp_path)
        info = loader._parse_skill_md(skill_md)
        assert info is None

    @pytest.mark.asyncio
    async def test_parse_optional_defaults(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            """---
name: minimal
description: 最小定义
---

body
""",
            encoding="utf-8",
        )

        loader, _ = await _make_loader(tmp_path)
        info = loader._parse_skill_md(skill_md)

        assert info is not None
        assert info.category == "custom"
        assert info.version == "0.0.0"
        assert info.author == "unknown"

    @pytest.mark.asyncio
    async def test_has_scripts(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            """---
name: with-script
description: 带脚本
---
body
""",
            encoding="utf-8",
        )
        (tmp_path / "deploy.sh").write_text("#!/bin/bash\necho ok")

        loader, _ = await _make_loader(tmp_path)
        info = loader._parse_skill_md(skill_md)

        assert info is not None
        assert info.has_scripts is True


# ─── 扫描测试 ─────────────────────────────────────────────


class TestScan:
    @pytest.mark.asyncio
    async def test_scan_directory(self, tmp_path: Path) -> None:
        # 创建两个 Skill
        for name in ("alpha", "beta"):
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {name} skill\n---\nbody",
                encoding="utf-8",
            )

        loader, store = await _make_loader(tmp_path)
        infos = await loader.scan()

        assert len(infos) == 2
        names = {i.name for i in infos}
        assert names == {"alpha", "beta"}

        # 数据库应有记录
        for name in names:
            state = await store.get(name)
            assert state is not None
            assert state.enabled is True

    @pytest.mark.asyncio
    async def test_scan_empty_directory(self, tmp_path: Path) -> None:
        loader, _ = await _make_loader(tmp_path)
        infos = await loader.scan()
        assert infos == []

    @pytest.mark.asyncio
    async def test_scan_nonexistent_directory(self, tmp_path: Path) -> None:
        loader, _ = await _make_loader(tmp_path / "nonexistent")
        infos = await loader.scan()
        assert infos == []

    @pytest.mark.asyncio
    async def test_scan_skips_invalid(self, tmp_path: Path) -> None:
        # 有效 Skill
        d1 = tmp_path / "valid"
        d1.mkdir()
        (d1 / "SKILL.md").write_text(
            "---\nname: valid\ndescription: ok\n---\nbody",
            encoding="utf-8",
        )
        # 无效 Skill（缺少 name）
        d2 = tmp_path / "invalid"
        d2.mkdir()
        (d2 / "SKILL.md").write_text(
            "---\ndescription: no name\n---\nbody",
            encoding="utf-8",
        )

        loader, _ = await _make_loader(tmp_path)
        infos = await loader.scan()

        assert len(infos) == 1
        assert infos[0].name == "valid"
