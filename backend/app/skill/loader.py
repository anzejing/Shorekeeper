"""SkillLoader — 扫描 SKILL.md 文件并解析。

职责：
1. 扫描 skills 目录下的 SKILL.md 文件
2. 解析 YAML frontmatter + Markdown body
3. 与 SkillStore 同步（新发现 / 已删除）

SKILL.md 格式兼容 skills.sh / Claude Code 规范：
- YAML frontmatter：name, description, category, version, author
- Markdown body：系统提示词
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.skill.models import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    SCRIPT_EXTENSIONS,
    SKILL_FILENAME,
    SkillInfo,
)
from app.skill.store import SQLiteSkillStore

log = logging.getLogger(__name__)


class SkillLoader:
    """扫描 skills 目录，解析 SKILL.md，同步到 Store。"""

    def __init__(
        self,
        skills_dir: Path,
        store: SQLiteSkillStore,
    ) -> None:
        self._skills_dir = skills_dir
        self._store = store

    async def scan(self) -> list[SkillInfo]:
        """扫描 skills 目录，解析所有 SKILL.md，同步到 Store。

        Returns:
            成功解析的 SkillInfo 列表。
        """
        if not self._skills_dir.exists():
            log.info("Skills 目录不存在: %s", self._skills_dir)
            return []

        discovered: list[SkillInfo] = []
        discovered_names: set[str] = set()

        # 遍历 skills/*/SKILL.md
        for skill_dir in sorted(self._skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / SKILL_FILENAME
            if not skill_md.exists():
                continue

            info = self._parse_skill_md(skill_md)
            if info is None:
                continue

            # 检查名称冲突
            if info.name in discovered_names:
                log.warning("Skill 名称冲突，跳过: %s (%s)", info.name, skill_md)
                continue

            discovered_names.add(info.name)
            discovered.append(info)

            # 同步到 Store（新 Skill 自动创建记录）
            await self._store.upsert(info.name)

        log.info("扫描完成: 发现 %d 个 Skill", len(discovered))
        return discovered

    async def load_skill(self, name: str) -> SkillInfo | None:
        """按名称加载单个 Skill。

        Args:
            name: Skill 名称。

        Returns:
            SkillInfo 或 None。
        """
        skill_dir = self._skills_dir / name
        skill_md = skill_dir / SKILL_FILENAME

        if not skill_md.exists():
            return None

        return self._parse_skill_md(skill_md)

    def _parse_skill_md(self, path: Path) -> SkillInfo | None:
        """解析 SKILL.md 文件。

        Args:
            path: SKILL.md 文件路径。

        Returns:
            SkillInfo 或 None（解析失败时）。
        """
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            log.exception("读取 SKILL.md 失败: %s", path)
            return None

        info = self._parse_skill_md_content(content)
        if info is None:
            return None

        # 补充文件相关字段
        parent_dir = path.parent
        has_scripts = any(
            f.suffix in SCRIPT_EXTENSIONS
            for f in parent_dir.iterdir()
            if f.is_file()
        )

        return SkillInfo(
            name=info.name,
            description=info.description,
            category=info.category,
            version=info.version,
            author=info.author,
            system_prompt=info.system_prompt,
            path=path,
            has_scripts=has_scripts,
        )

    def _parse_skill_md_content(self, content: str) -> SkillInfo | None:
        """从字符串解析 SKILL.md 内容（用于安装时预解析）。

        Args:
            content: SKILL.md 文件内容。

        Returns:
            SkillInfo（path 为 Path()，has_scripts 为 False）或 None。
        """
        # 分离 frontmatter 和 body
        frontmatter, body = self._split_frontmatter(content)
        if frontmatter is None:
            log.warning("SKILL.md 缺少 frontmatter")
            return None

        # 检查必填字段
        missing = REQUIRED_FIELDS - set(frontmatter.keys())
        if missing:
            log.warning("SKILL.md 缺少必填字段: %s", missing)
            return None

        # version 兼容（Agent Plugins 规范）：metadata.version → 顶层 version → 默认值
        if "version" not in frontmatter:
            metadata = frontmatter.get("metadata")
            if isinstance(metadata, dict) and metadata.get("version"):
                frontmatter["version"] = metadata["version"]

        # 填充可选字段默认值
        for key, default in OPTIONAL_FIELDS.items():
            if key not in frontmatter:
                frontmatter[key] = default

        return SkillInfo(
            name=frontmatter["name"],
            description=frontmatter["description"],
            category=frontmatter["category"],
            version=frontmatter["version"],
            author=frontmatter["author"],
            system_prompt=body.strip(),
            path=Path(),
            has_scripts=False,
        )

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[dict[str, Any] | None, str]:
        """分离 YAML frontmatter 和 Markdown body。

        格式：
        ---
        key: value
        ---
        body content

        Returns:
            (frontmatter_dict, body_string) 或 (None, content)。
        """
        if not content.startswith("---"):
            return None, content

        # 找第二个 ---
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return None, content

        yaml_str = content[3:end_idx]
        body = content[end_idx + 3:]

        try:
            frontmatter = yaml.safe_load(yaml_str)
            if not isinstance(frontmatter, dict):
                return None, content
            return frontmatter, body
        except yaml.YAMLError:
            log.warning("YAML frontmatter 解析失败")
            return None, content
