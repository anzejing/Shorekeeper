"""Skill API 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.skill import init_skill_api, router as skill_router
from app.runtime.store import init_db
from app.plugin.loader import PluginLoader
from app.skill.loader import SkillLoader
from app.skill.service import SkillService
from app.skill.store import SQLiteSkillStore, init_skill_db


# ─── 辅助 ─────────────────────────────────────────────────


async def _setup(skills_dir: Path) -> tuple[SkillService, FastAPI]:
    """创建测试专用 app（不触发 main.py 的 lifespan）。"""
    db = await init_db()
    await init_skill_db(db)
    store = SQLiteSkillStore(db)
    loader = SkillLoader(skills_dir, store)
    plugin_loader = PluginLoader(skills_dir.parent / "plugins", loader, store)
    service = SkillService(store, loader, plugin_loader)
    await service.initialize()
    init_skill_api(service)

    # 测试专用 app，不含 lifespan
    test_app = FastAPI()
    test_app.include_router(skill_router)
    return service, test_app


def _write_skill(skills_dir: Path, name: str, description: str = "test") -> None:
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\ncategory: utility\n---\n\n# {name}\n\n提示词内容。",
        encoding="utf-8",
    )


# ─── 测试 ─────────────────────────────────────────────────


class TestListSkills:
    @pytest.mark.asyncio
    async def test_list_skills(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "alpha")
        _write_skill(tmp_path, "beta")
        _, app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/skills")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert {s["name"] for s in data["skills"]} == {"alpha", "beta"}

    @pytest.mark.asyncio
    async def test_list_empty(self, tmp_path: Path) -> None:
        _, app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/skills")

        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestGetSkill:
    @pytest.mark.asyncio
    async def test_get_skill(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "memory", "记忆管理")
        _, app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/skills/memory")

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "memory"
        assert data["description"] == "记忆管理"
        assert data["enabled"] is True
        assert "提示词内容" in data["system_prompt"]

    @pytest.mark.asyncio
    async def test_get_not_found(self, tmp_path: Path) -> None:
        _, app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/skills/nonexistent")

        assert resp.status_code == 404


class TestUpdateSkill:
    @pytest.mark.asyncio
    async def test_disable_skill(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "memory")
        _, app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch(
                "/api/skills/memory",
                json={"enabled": False},
            )

        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    @pytest.mark.asyncio
    async def test_update_config(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "memory")
        _, app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch(
                "/api/skills/memory",
                json={"config": {"key": "value"}},
            )

        assert resp.status_code == 200
        assert resp.json()["config"] == {"key": "value"}


class TestInstallSkill:
    @pytest.mark.asyncio
    async def test_install_skill(self, tmp_path: Path) -> None:
        _, app = await _setup(tmp_path)

        skill_md = """---
name: new-skill
description: 新安装的 Skill
category: custom
---

# New Skill

安装的提示词。
"""

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/skills/install",
                files={"file": ("SKILL.md", skill_md.encode(), "text/markdown")},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "skill"
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "new-skill"
        assert data["skills"][0]["enabled"] is True

        # 验证文件已写入
        assert (tmp_path / "new-skill" / "SKILL.md").exists()


class TestReloadSkills:
    @pytest.mark.asyncio
    async def test_reload(self, tmp_path: Path) -> None:
        _, app = await _setup(tmp_path)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 初始为空
            resp = await client.get("/api/skills")
            assert resp.json()["total"] == 0

            # 手动添加 Skill 文件
            _write_skill(tmp_path, "manual", "手动安装")

            # 刷新
            resp = await client.post("/api/skills/reload")
            assert resp.status_code == 200
            assert resp.json()["total"] == 1
            assert resp.json()["skills"][0]["name"] == "manual"
