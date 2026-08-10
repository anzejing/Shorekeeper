"""SkillService.get_skill_summaries 测试。"""

from __future__ import annotations

import pytest

from app.skill.models import SkillInfo, SkillState
from app.skill.service import SkillService


# ─── 辅助 ─────────────────────────────────────────────────


class MockSkillStore:
    """模拟 SkillStore。"""

    def __init__(self, states: list[SkillState] | None = None) -> None:
        self._states = {s.name: s for s in (states or [])}

    async def list(self, enabled: bool | None = None) -> list[SkillState]:
        states = list(self._states.values())
        if enabled is not None:
            states = [s for s in states if s.enabled == enabled]
        return states


class MockSkillLoader:
    _skills_dir = "/fake/skills"


class MockPluginLoader:
    _plugins_dir = "/fake/plugins"


def _make_service(infos: list[SkillInfo], states: list[SkillState]) -> SkillService:
    """创建带预设数据的 SkillService。"""
    store = MockSkillStore(states)
    service = SkillService.__new__(SkillService)
    service._store = store
    service._loader = MockSkillLoader()
    service._plugin_loader = MockPluginLoader()
    service._info_cache = {info.name: info for info in infos}
    return service


def _make_info(name: str, description: str, system_prompt: str = "") -> SkillInfo:
    from pathlib import Path
    return SkillInfo(
        name=name,
        description=description,
        category="custom",
        version="1.0",
        author="test",
        system_prompt=system_prompt,
        path=Path(f"/fake/{name}/SKILL.md"),
    )


# ─── 测试 ─────────────────────────────────────────────────


class TestGetSkillSummaries:
    @pytest.mark.asyncio
    async def test_returns_summaries(self) -> None:
        infos = [
            _make_info("code_review", "代码审查"),
            _make_info("deploy", "部署应用"),
        ]
        states = [
            SkillState(name="code_review", enabled=True),
            SkillState(name="deploy", enabled=True),
        ]
        service = _make_service(infos, states)

        result = await service.get_skill_summaries()

        assert "code_review" in result
        assert "代码审查" in result
        assert "deploy" in result
        assert "部署应用" in result

    @pytest.mark.asyncio
    async def test_has_header(self) -> None:
        infos = [_make_info("test", "测试")]
        states = [SkillState(name="test", enabled=True)]
        service = _make_service(infos, states)

        result = await service.get_skill_summaries()

        assert "可用技能索引" in result
        assert "tool_search" in result

    @pytest.mark.asyncio
    async def test_empty_when_no_skills(self) -> None:
        service = _make_service([], [])

        result = await service.get_skill_summaries()

        assert result == ""

    @pytest.mark.asyncio
    async def test_only_enabled_skills(self) -> None:
        infos = [
            _make_info("active", "活跃技能"),
            _make_info("disabled", "禁用技能"),
        ]
        states = [
            SkillState(name="active", enabled=True),
            SkillState(name="disabled", enabled=False),
        ]
        service = _make_service(infos, states)

        result = await service.get_skill_summaries()

        assert "active" in result
        assert "disabled" not in result
