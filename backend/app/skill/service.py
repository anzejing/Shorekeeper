"""SkillService — Skill 模块业务服务。

合并 SkillInfo（文件内容）和 SkillState（数据库状态），
对外提供统一的 Skill 管理接口。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from app.skill.loader import SkillLoader
from app.skill.models import (
    SKILL_FILENAME,
    SkillInfo,
    SkillListResponse,
    SkillResponse,
    SkillState,
)
from app.skill.store import SQLiteSkillStore

log = logging.getLogger(__name__)


class SkillService:
    """Skill 业务服务。

    职责：
    1. 合并文件内容 + 数据库状态，返回完整 Skill 信息
    2. 收集所有 enabled Skill 的 system_prompt
    3. Skill 安装/卸载
    4. Skill 状态管理（enabled, config）
    """

    def __init__(
        self,
        store: SQLiteSkillStore,
        loader: SkillLoader,
    ) -> None:
        self._store = store
        self._loader = loader
        # 内存缓存：name → SkillInfo（启动时加载）
        self._info_cache: dict[str, SkillInfo] = {}

    async def initialize(self) -> None:
        """启动时调用：扫描 skills 目录，加载所有 Skill。"""
        infos = await self._loader.scan()
        self._info_cache = {info.name: info for info in infos}
        log.info("SkillService 初始化完成: %d 个 Skill", len(self._info_cache))

    # ─── Prompt 注入 ─────────────────────────────────────

    async def get_system_prompts(self) -> list[str]:
        """收集所有 enabled Skill 的 system_prompt。

        Returns:
            系统提示词列表（每个 Skill 一个字符串）。
        """
        states = await self._store.list(enabled=True)
        prompts: list[str] = []

        for state in states:
            info = self._info_cache.get(state.name)
            if info and info.system_prompt:
                prompts.append(info.system_prompt)

        return prompts

    # ─── 查询 ────────────────────────────────────────────

    async def list_skills(
        self,
        enabled: bool | None = None,
    ) -> SkillListResponse:
        """列出 Skill。"""
        states = await self._store.list(enabled=enabled)
        responses: list[SkillResponse] = []

        for state in states:
            info = self._info_cache.get(state.name)
            if info:
                responses.append(_merge_to_response(info, state))

        return SkillListResponse(skills=responses, total=len(responses))

    async def get_skill(self, name: str) -> SkillResponse | None:
        """获取 Skill 详情。"""
        info = self._info_cache.get(name)
        if info is None:
            return None

        state = await self._store.get(name)
        if state is None:
            # 文件存在但数据库无记录，创建
            state = await self._store.upsert(name)

        return _merge_to_response(info, state)

    # ─── 状态管理 ────────────────────────────────────────

    async def update_skill(
        self,
        name: str,
        enabled: bool | None = None,
        config: dict[str, Any] | None = None,
    ) -> SkillResponse:
        """更新 Skill 状态。"""
        # 确保存在
        if name not in self._info_cache:
            raise KeyError(f"Skill 不存在: {name}")

        fields: dict[str, Any] = {}
        if enabled is not None:
            fields["enabled"] = enabled
        if config is not None:
            fields["config"] = config

        if fields:
            state = await self._store.update(name, **fields)
        else:
            state = await self._store.get(name)
            if state is None:
                state = await self._store.upsert(name)

        info = self._info_cache[name]
        return _merge_to_response(info, state)

    # ─── 安装/卸载 ───────────────────────────────────────

    async def install_skill(
        self,
        skill_md_content: str,
        attachments: dict[str, bytes] | None = None,
        target_name: str | None = None,
    ) -> SkillResponse:
        """安装 Skill（写入文件 + 同步数据库）。

        Args:
            skill_md_content: SKILL.md 文件内容。
            attachments: 附带文件（filename → content）。
            target_name: 目标目录名（不填则从 frontmatter 的 name 取）。

        Returns:
            安装后的 SkillResponse。
        """
        # 解析 frontmatter 获取 name
        info = self._loader._parse_skill_md_content(skill_md_content)
        if info is None:
            raise ValueError("SKILL.md 解析失败：缺少必填字段")

        dir_name = target_name or info.name
        skill_dir = self._loader._skills_dir / dir_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        # 写入 SKILL.md
        skill_md_path = skill_dir / SKILL_FILENAME
        skill_md_path.write_text(skill_md_content, encoding="utf-8")

        # 写入附带文件
        if attachments:
            for filename, content in attachments.items():
                (skill_dir / filename).write_bytes(content)

        # 重新解析（获取正确的 path 和 has_scripts）
        info = self._loader._parse_skill_md(skill_md_path)
        if info is None:
            raise ValueError("SKILL.md 写入后解析失败")

        # 同步数据库
        await self._store.upsert(info.name)
        self._info_cache[info.name] = info

        state = await self._store.get(info.name)
        return _merge_to_response(info, state)

    async def uninstall_skill(self, name: str) -> bool:
        """卸载 Skill（删除文件 + 数据库记录）。

        Args:
            name: Skill 名称。

        Returns:
            是否成功卸载。
        """
        info = self._info_cache.get(name)

        # 删除文件
        if info and info.path.parent.exists():
            shutil.rmtree(info.path.parent)
            log.info("删除 Skill 目录: %s", info.path.parent)

        # 删除数据库记录
        deleted = await self._store.delete(name)

        # 清除缓存
        self._info_cache.pop(name, None)

        return deleted

    # ─── 刷新 ────────────────────────────────────────────

    async def reload(self) -> None:
        """重新扫描 skills 目录（用于手动安装 Skill 后刷新）。"""
        infos = await self._loader.scan()
        self._info_cache = {info.name: info for info in infos}


# ─── 辅助函数 ─────────────────────────────────────────────


def _merge_to_response(info: SkillInfo, state: SkillState) -> SkillResponse:
    """合并 SkillInfo 和 SkillState 为 SkillResponse。"""
    return SkillResponse(
        name=info.name,
        description=info.description,
        category=info.category,
        version=info.version,
        author=info.author,
        enabled=state.enabled,
        system_prompt=info.system_prompt,
        path=str(info.path),
        has_scripts=info.has_scripts,
        config=state.config,
        installed_at=state.installed_at,
    )
