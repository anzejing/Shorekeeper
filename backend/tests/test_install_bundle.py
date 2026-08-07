"""统一安装入口测试（SKILL.md / zip / tar.gz 自动判断 + 安全防护）。"""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.skill import init_skill_api, router as skill_router
from app.plugin.installer import MAX_ENTRIES, MAX_TOTAL_SIZE
from app.runtime.store import init_db
from app.skill.loader import SkillLoader
from app.skill.service import SkillService
from app.skill.store import SQLiteSkillStore, init_skill_db
from app.plugin.loader import PluginLoader

MANIFEST = {
    "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
    "name": "test-plugin",
    "version": "1.0.0",
    "description": "测试插件",
}

SKILL_MD = """---
name: test-skill
description: 测试 Skill
category: utility
---

# Test Skill

测试提示词。
"""


# ─── 辅助 ─────────────────────────────────────────────────


async def _setup(
    tmp_path: Path,
) -> tuple[FastAPI, Path, Path]:
    db = await init_db()
    await init_skill_db(db)
    store = SQLiteSkillStore(db)
    skills_dir = tmp_path / "skills"
    loader = SkillLoader(skills_dir, store)
    plugins_dir = tmp_path / "plugins"
    plugin_loader = PluginLoader(plugins_dir, loader, store)
    service = SkillService(store, loader, plugin_loader)
    await service.initialize()
    init_skill_api(service)

    test_app = FastAPI()
    test_app.include_router(skill_router)
    return test_app, skills_dir, plugins_dir


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _make_targz(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            data = content
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _plugin_files(plugin_name: str = "test-plugin") -> dict[str, bytes]:
    return {
        "plugin.json": json.dumps(MANIFEST).encode(),
        "skills/greet/SKILL.md": (
            "---\nname: greet\ndescription: plugin greet\n---\n\nGreet the user.\n"
        ).encode(),
        "skills/translate/SKILL.md": (
            "---\nname: translate\ndescription: plugin translate\n---\n\nTranslate.\n"
        ).encode(),
    }


async def _post_install(
    app: FastAPI, filename: str, content: bytes
) -> tuple[int, dict]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/skills/install",
            files={"file": (filename, content, "application/octet-stream")},
        )
    return resp.status_code, resp.json()


# ─── 单 SKILL.md ──────────────────────────────────────────


class TestSingleSkillMd:
    @pytest.mark.asyncio
    async def test_install_md_file(self, tmp_path: Path) -> None:
        app, skills_dir, _ = await _setup(tmp_path)
        status, data = await _post_install(app, "SKILL.md", SKILL_MD.encode())

        assert status == 201
        assert data["type"] == "skill"
        assert data["skills"][0]["name"] == "test-skill"
        assert (skills_dir / "test-skill" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_install_md_with_target_name(self, tmp_path: Path) -> None:
        app, skills_dir, _ = await _setup(tmp_path)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/skills/install",
                files={"file": ("SKILL.md", SKILL_MD.encode(), "text/markdown")},
                data={"target_name": "custom-dir"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "skill"
        assert (skills_dir / "custom-dir" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_install_invalid_format(self, tmp_path: Path) -> None:
        """非 md / 非压缩包 → 400。"""
        app, _, _ = await _setup(tmp_path)
        status, data = await _post_install(app, "notes.txt", b"just some text")

        assert status == 400
        assert "不支持的文件格式" in data["detail"]


# ─── zip / tar.gz 插件 ────────────────────────────────────


class TestPluginInstall:
    @pytest.mark.asyncio
    async def test_install_plugin_zip(self, tmp_path: Path) -> None:
        app, _, plugins_dir = await _setup(tmp_path)
        status, data = await _post_install(app, "test-plugin.zip", _make_zip(_plugin_files()))

        assert status == 201
        assert data["type"] == "plugin"
        assert data["plugin_name"] == "test-plugin"
        assert {s["name"] for s in data["skills"]} == {
            "test-plugin/greet",
            "test-plugin/translate",
        }
        # 插件目录已写入
        assert (plugins_dir / "test-plugin" / "plugin.json").exists()
        assert (plugins_dir / "test-plugin" / "skills" / "greet" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_install_plugin_targz(self, tmp_path: Path) -> None:
        app, _, plugins_dir = await _setup(tmp_path)
        status, data = await _post_install(
            app, "test-plugin.tar.gz", _make_targz(_plugin_files())
        )

        assert status == 201
        assert data["type"] == "plugin"
        assert data["plugin_name"] == "test-plugin"
        assert (plugins_dir / "test-plugin" / "plugin.json").exists()

    @pytest.mark.asyncio
    async def test_install_skill_dir_zip(self, tmp_path: Path) -> None:
        """skill 目录打包（xxx/SKILL.md）→ 独立 skill。"""
        app, skills_dir, _ = await _setup(tmp_path)
        files = {
            "my-skill/SKILL.md": SKILL_MD.encode(),
            "my-skill/scripts/run.sh": b"#!/bin/sh\necho hi",
        }
        status, data = await _post_install(app, "my-skill.zip", _make_zip(files))

        assert status == 201
        assert data["type"] == "skill"
        assert data["skills"][0]["name"] == "test-skill"
        # 附带脚本已写入
        assert (skills_dir / "test-skill" / "scripts" / "run.sh").exists()

    @pytest.mark.asyncio
    async def test_install_skill_root_zip(self, tmp_path: Path) -> None:
        """zip 根目录直接含 SKILL.md。"""
        app, skills_dir, _ = await _setup(tmp_path)
        files = {"SKILL.md": SKILL_MD.encode()}
        status, data = await _post_install(app, "skill-root.zip", _make_zip(files))

        assert status == 201
        assert data["type"] == "skill"
        assert data["skills"][0]["name"] == "test-skill"
        assert (skills_dir / "test-skill" / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_install_unrecognized_structure(self, tmp_path: Path) -> None:
        """zip 不含 plugin.json / SKILL.md → 400。"""
        app, _, _ = await _setup(tmp_path)
        files = {"readme.txt": b"nothing useful"}
        status, data = await _post_install(app, "random.zip", _make_zip(files))

        assert status == 400
        assert "无法识别" in data["detail"]

    @pytest.mark.asyncio
    async def test_install_invalid_plugin_manifest(self, tmp_path: Path) -> None:
        """zip 内 plugin.json 校验失败 → 400。"""
        app, _, _ = await _setup(tmp_path)
        files = {"plugin.json": json.dumps({"name": "bad"}).encode()}
        status, data = await _post_install(app, "bad.zip", _make_zip(files))

        assert status == 400
        assert "插件清单" in data["detail"]

    @pytest.mark.asyncio
    async def test_install_duplicate_plugin(self, tmp_path: Path) -> None:
        """同名插件重复安装 → 400。"""
        app, _, _ = await _setup(tmp_path)
        await _post_install(app, "test-plugin.zip", _make_zip(_plugin_files()))
        status, data = await _post_install(app, "test-plugin.zip", _make_zip(_plugin_files()))

        assert status == 400
        assert "已存在" in data["detail"]


# ─── 安全防护 ─────────────────────────────────────────────


class TestSecurity:
    @pytest.mark.asyncio
    async def test_zip_slip_rejected(self, tmp_path: Path) -> None:
        """zip slip（../ 逃逸）→ 400。"""
        app, _, _ = await _setup(tmp_path)
        files = {
            "plugin.json": json.dumps(MANIFEST).encode(),
            "../evil.txt": b"evil",
        }
        status, data = await _post_install(app, "evil.zip", _make_zip(files))

        assert status == 400
        assert "非法路径" in data["detail"]

    @pytest.mark.asyncio
    async def test_zip_absolute_path_rejected(self, tmp_path: Path) -> None:
        """zip 绝对路径条目 → 400。"""
        app, _, _ = await _setup(tmp_path)
        files = {
            "plugin.json": json.dumps(MANIFEST).encode(),
            "/etc/passwd": b"evil",
        }
        status, data = await _post_install(app, "evil.zip", _make_zip(files))

        assert status == 400
        assert "非法路径" in data["detail"]

    @pytest.mark.asyncio
    async def test_zip_bomb_rejected(self, tmp_path: Path, monkeypatch) -> None:
        """超过大小限制 → 400。"""
        app, _, _ = await _setup(tmp_path)
        # 缩小限制以便测试
        monkeypatch.setattr("app.plugin.installer.MAX_TOTAL_SIZE", 10)

        files = {"big.txt": b"x" * 100}
        status, data = await _post_install(app, "bomb.zip", _make_zip(files))

        assert status == 400
        assert "大小限制" in data["detail"]

    @pytest.mark.asyncio
    async def test_tar_symlink_rejected(self, tmp_path: Path) -> None:
        """tar 符号链接 → 400。"""
        app, _, _ = await _setup(tmp_path)

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)

        status, data = await _post_install(app, "evil.tar.gz", buf.getvalue())

        assert status == 400
        assert "符号链接" in data["detail"]


# ─── 插件删除 ─────────────────────────────────────────────


class TestPluginDelete:
    @pytest.mark.asyncio
    async def test_delete_plugin(self, tmp_path: Path) -> None:
        app, _, plugins_dir = await _setup(tmp_path)
        await _post_install(app, "test-plugin.zip", _make_zip(_plugin_files()))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/skills/plugins/test-plugin")

        assert resp.status_code == 204
        assert not (plugins_dir / "test-plugin").exists()

        # 插件 skill 不再出现在列表中
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/skills")
        names = [s["name"] for s in resp.json()["skills"]]
        assert "test-plugin/greet" not in names

    @pytest.mark.asyncio
    async def test_delete_nonexistent_plugin(self, tmp_path: Path) -> None:
        app, _, _ = await _setup(tmp_path)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/skills/plugins/no-such-plugin")

        assert resp.status_code == 404
