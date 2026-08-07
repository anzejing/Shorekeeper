"""PluginLoader — 扫描插件目录，发现 Agent Plugins 插件中的 Skills。

遵循 Agent Plugins v1.0.0 规范：
- §6.1 固定位置：skills/ 下的子目录含 SKILL.md
- §6.2 缺失位置不算错误；无效组件跳过，不影响其他组件
- §7.1 skill 不递归搜索更深层
- §4.1 路径安全：解析路径必须留在插件根内
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from app.plugin.manifest import ManifestError, PluginManifest, load_manifest
from app.skill.loader import SkillLoader
from app.skill.models import SKILL_FILENAME, SkillInfo
from app.skill.store import SQLiteSkillStore

log = logging.getLogger(__name__)


class PluginLoader:
    """扫描插件目录，发现插件中的 Skill 并转换为带命名空间的 SkillInfo。"""

    def __init__(
        self,
        plugins_dir: Path,
        skill_loader: SkillLoader,
        store: SQLiteSkillStore | None = None,
    ) -> None:
        self._plugins_dir = plugins_dir
        self._skill_loader = skill_loader
        self._store = store

    async def scan(self) -> list[SkillInfo]:
        """扫描插件目录，返回所有插件的 Skill（逻辑名 = 'plugin-name/skill-name'）。

        Returns:
            带命名空间的 SkillInfo 列表。
        """
        if not self._plugins_dir.exists():
            log.info("Plugins 目录不存在: %s", self._plugins_dir)
            return []

        results: list[SkillInfo] = []

        for plugin_dir in sorted(self._plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue

            # 校验 plugin.json（§5.1 / §4.1）
            manifest_path = plugin_dir / "plugin.json"
            if not manifest_path.exists():
                # §6.2 缺失位置不算错误
                log.info("跳过无 plugin.json 的目录: %s", plugin_dir.name)
                continue

            try:
                manifest = load_manifest(manifest_path)
            except ManifestError as e:
                # §11.3 单个插件失败不阻塞其他插件
                log.warning("跳过无效插件 %s: %s", plugin_dir.name, e)
                continue

            # 发现 skills（§6.1）
            try:
                skills = await self._discover_skills(plugin_dir, manifest)
            except Exception:
                log.exception("插件 %s 的 skills 发现失败", manifest.name)
                continue

            results.extend(skills)
            log.info(
                "插件 %s 发现 %d 个 Skill", manifest.name, len(skills)
            )

        return results

    async def _discover_skills(
        self, plugin_dir: Path, manifest: PluginManifest
    ) -> list[SkillInfo]:
        """发现插件 skills/ 下的所有 Skill（§7.1 不递归）。"""
        skills_dir = plugin_dir / "skills"
        if not skills_dir.is_dir():
            return []

        found: list[SkillInfo] = []
        plugin_root = plugin_dir.resolve()

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / SKILL_FILENAME
            if not skill_md.exists():
                continue

            # §4.1 路径安全：解析后的路径必须留在插件根内
            if not _is_within(skill_md.resolve(), plugin_root):
                log.warning(
                    "插件 %s 的 Skill 路径逃逸插件根，跳过: %s",
                    manifest.name,
                    skill_md,
                )
                continue

            info = self._skill_loader._parse_skill_md(skill_md)
            if info is None:
                # §7.1 无效 skill 跳过，继续其他组件
                log.warning(
                    "插件 %s 的 Skill 解析失败，跳过: %s",
                    manifest.name,
                    skill_md,
                )
                continue

            # 命名空间：逻辑名 = plugin-name/skill-name
            info = replace(
                info,
                name=f"{manifest.name}/{info.name}",
                plugin_name=manifest.name,
            )
            found.append(info)

            # 同步到 Store（与 SkillLoader 一致：新 Skill 自动创建记录）
            if self._store is not None:
                await self._store.upsert(info.name)

        return found


def _is_within(path: Path, root: Path) -> bool:
    """检查 path 是否在 root 内（路径安全 §4.1）。"""
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False
