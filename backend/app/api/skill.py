"""Skill HTTP API。

提供 Skill 管理、安装、卸载的 REST 接口。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.skill.models import SkillListResponse, SkillResponse, UpdateSkillRequest
from app.skill.service import SkillService

router = APIRouter(prefix="/api/skills", tags=["skills"])

# SkillService 实例由 main.py 注入
_service: SkillService | None = None


def init_skill_api(service: SkillService) -> None:
    """初始化 Skill API，注入 SkillService。"""
    global _service
    _service = service


def _get_service() -> SkillService:
    """获取 SkillService 实例。"""
    if _service is None:
        raise HTTPException(status_code=503, detail="Skill 模块未初始化")
    return _service


# ─── Skill 管理 ──────────────────────────────────────────


@router.get("", response_model=SkillListResponse)
async def list_skills(
    enabled: bool | None = None,
) -> SkillListResponse:
    """列出 Skill。"""
    service = _get_service()
    return await service.list_skills(enabled=enabled)


@router.get("/{name}", response_model=SkillResponse)
async def get_skill(name: str) -> SkillResponse:
    """获取 Skill 详情。"""
    service = _get_service()
    result = await service.get_skill(name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}")
    return result


@router.patch("/{name}", response_model=SkillResponse)
async def update_skill(
    name: str,
    request: UpdateSkillRequest,
) -> SkillResponse:
    """更新 Skill 状态（启用/禁用、配置）。"""
    service = _get_service()
    try:
        return await service.update_skill(
            name=name,
            enabled=request.enabled,
            config=request.config,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}")


# ─── 安装/卸载 ───────────────────────────────────────────


@router.post("/install", response_model=SkillResponse, status_code=201)
async def install_skill(
    skill_md: UploadFile = File(description="SKILL.md 文件"),
    target_name: str | None = Form(default=None, description="目标目录名"),
) -> SkillResponse:
    """安装 Skill（上传 SKILL.md 文件）。"""
    service = _get_service()

    try:
        content = (await skill_md.read()).decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="SKILL.md 必须是 UTF-8 编码")

    try:
        return await service.install_skill(
            skill_md_content=content,
            target_name=target_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{name}", status_code=204)
async def uninstall_skill(name: str) -> None:
    """卸载 Skill（删除文件和数据库记录）。"""
    service = _get_service()
    deleted = await service.uninstall_skill(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}")


# ─── 刷新 ────────────────────────────────────────────────


@router.post("/reload", response_model=SkillListResponse)
async def reload_skills() -> SkillListResponse:
    """重新扫描 skills 目录（手动安装 Skill 后调用）。"""
    service = _get_service()
    await service.reload()
    return await service.list_skills()
